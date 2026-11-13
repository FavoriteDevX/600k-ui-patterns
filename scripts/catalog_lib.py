"""Shared helpers for reading, writing and validating the sharded catalog.

The catalog lives in data/catalog/part-NNNNN.jsonl, one record per line,
SHARD_SIZE records per file. Only metadata is stored; images live elsewhere.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_DIR = REPO_ROOT / "data" / "catalog"
SCHEMA_PATH = REPO_ROOT / "schemas" / "ui-screen.schema.json"
SHARD_SIZE = 50_000
SHARD_RE = re.compile(r"^part-(\d{5})\.jsonl$")

PLATFORM_ALIASES = {
    "ios": "iOS",
    "iphone": "iOS",
    "ipad": "iOS",
    "android": "Android",
    "web": "Web",
    "website": "Web",
    "desktop": "Desktop",
    "macos": "Desktop",
    "windows": "Desktop",
    "linux": "Desktop",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif", ".tif", ".tiff"}


def normalize_platform(value: str | None, default: str = "Web") -> str:
    if not value:
        return default
    return PLATFORM_ALIASES.get(value.strip().lower(), value.strip())


def shard_paths(catalog_dir: Path = CATALOG_DIR) -> list[Path]:
    if not catalog_dir.exists():
        return []
    return sorted(p for p in catalog_dir.iterdir() if SHARD_RE.match(p.name))


def iter_records(catalog_dir: Path = CATALOG_DIR) -> Iterator[tuple[Path, int, dict]]:
    """Yield (shard_path, line_number, record) for every record in the catalog."""
    for path in shard_paths(catalog_dir):
        with path.open(encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if line:
                    yield path, lineno, json.loads(line)


class CatalogWriter:
    """Appends records to the sharded catalog, assigning sequential ids and
    skipping records whose (source.name, source.record_id) already exist."""

    def __init__(self, catalog_dir: Path = CATALOG_DIR, shard_size: int = SHARD_SIZE):
        self.catalog_dir = catalog_dir
        self.shard_size = shard_size
        self.catalog_dir.mkdir(parents=True, exist_ok=True)
        self.max_id = 0
        self.total = 0
        self.seen: set[tuple[str, str]] = set()
        for _, _, rec in iter_records(catalog_dir):
            self.total += 1
            self.max_id = max(self.max_id, int(rec["id"].split("_", 1)[1]))
            key = self._key(rec)
            if key:
                self.seen.add(key)
        self.added = 0
        self.skipped = 0

    @staticmethod
    def _key(rec: dict) -> tuple[str, str] | None:
        src = rec.get("source") or {}
        if src.get("record_id"):
            return (src["name"], str(src["record_id"]))
        return None

    def is_duplicate(self, rec: dict) -> bool:
        key = self._key(rec)
        return key is not None and key in self.seen

    def next_id(self) -> str:
        return f"ui_{self.max_id + 1:06d}"

    def append(self, rec: dict) -> bool:
        """Assign an id (if missing) and append. Returns False for duplicates."""
        if self.is_duplicate(rec):
            self.skipped += 1
            return False
        if not rec.get("id"):
            rec = {"id": self.next_id(), **rec}
        self.max_id = max(self.max_id, int(rec["id"].split("_", 1)[1]))
        shard = self.catalog_dir / f"part-{self.total // self.shard_size:05d}.jsonl"
        with shard.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
        key = self._key(rec)
        if key:
            self.seen.add(key)
        self.total += 1
        self.added += 1
        return True


def load_validator():
    import jsonschema  # imported lazily so the importer runs without it

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())


def validation_errors(validator, rec: dict) -> list[str]:
    return [
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in validator.iter_errors(rec)
    ]


def split_tags(raw: str | Iterable[str] | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        items = raw.split(",")
    else:
        items = raw
    return [t.strip() for t in items if t and str(t).strip()]
