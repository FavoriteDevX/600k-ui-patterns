#!/usr/bin/env python3
"""Bulk-import UI screen metadata into data/catalog/*.jsonl.

Only metadata is written to the repository. Images stay where they are hosted,
or are copied to S3-compatible object storage with --mirror (see storage.py).
Every record must carry a source and a license; rows without one are rejected.

Two importers:

  csv  Your own CSV (e.g. screenshots you captured, or a dataset export).
  hf   Any image dataset on the Hugging Face Hub, read through the public
       datasets-server API. The dataset license is read from its card.

Examples:

  python scripts/import_dataset.py csv screens.csv \
      --source-name "My captures" --source-url https://example.com \
      --license CC-BY-4.0

  python scripts/import_dataset.py hf HuggingFaceM4/WebSight --config v0.2 \
      --map ui_code_snippet=text --set app_name="WebSight (synthetic)" \
      --set category=Landing --set platform=Web --set flow=Landing \
      --image-column image --mirror --limit 1000
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from catalog_lib import (  # noqa: E402
    CatalogWriter,
    load_validator,
    normalize_platform,
    split_tags,
    validation_errors,
)

HF_API = "https://huggingface.co/api/datasets/"
HF_ROWS = "https://datasets-server.huggingface.co/rows"
HF_PAGE = 100
USER_AGENT = "600k-ui-patterns-importer/1.0"

# Hugging Face card license ids -> SPDX identifiers.
HF_LICENSE_TO_SPDX = {
    "mit": "MIT",
    "apache-2.0": "Apache-2.0",
    "cc0-1.0": "CC0-1.0",
    "cc-by-4.0": "CC-BY-4.0",
    "cc-by-3.0": "CC-BY-3.0",
    "cc-by-sa-4.0": "CC-BY-SA-4.0",
    "cc-by-sa-3.0": "CC-BY-SA-3.0",
    "cc-by-nc-4.0": "CC-BY-NC-4.0",
    "cc-by-nc-sa-4.0": "CC-BY-NC-SA-4.0",
    "odc-by": "ODC-By-1.0",
    "odbl": "ODbL-1.0",
    "pddl": "PDDL-1.0",
    "bsd-3-clause": "BSD-3-Clause",
    "openrail": "LicenseRef-OpenRAIL",
}
UNUSABLE_LICENSES = {"", "other", "unknown", "none"}

TEXT_FIELDS = ("app_name", "category", "platform", "flow", "step", "tags", "ui_code_snippet")


# --------------------------------------------------------------------------- helpers


def http_json(url: str, retries: int = 5) -> dict:
    delay = 2.0
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            body = exc.read().decode("utf-8", "replace")[:300]
            raise SystemExit(f"HTTP {exc.code} for {url}: {body}") from exc
        except urllib.error.URLError as exc:
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise SystemExit(f"Network error for {url}: {exc.reason}") from exc
    raise AssertionError("unreachable")


def parse_pairs(pairs: list[str], flag: str) -> dict[str, str]:
    out = {}
    for item in pairs or []:
        if "=" not in item:
            raise SystemExit(f"{flag} expects key=value, got: {item}")
        key, value = item.split("=", 1)
        key = key.strip()
        if key not in TEXT_FIELDS:
            raise SystemExit(f"{flag}: unknown field '{key}'. Allowed: {', '.join(TEXT_FIELDS)}")
        out[key] = value
    return out


def build_record(fields: dict, image_url: str, source: dict, license_: dict) -> dict:
    rec = {
        "app_name": str(fields.get("app_name") or "").strip(),
        "category": str(fields.get("category") or "").strip(),
        "platform": normalize_platform(fields.get("platform")),
        "flow": str(fields.get("flow") or "").strip(),
    }
    step = fields.get("step")
    if step not in (None, ""):
        try:
            rec["step"] = int(step)
        except (TypeError, ValueError):
            pass
    tags = split_tags(fields.get("tags"))
    if tags:
        rec["tags"] = tags
    rec["image_url"] = image_url
    snippet = fields.get("ui_code_snippet")
    if snippet:
        rec["ui_code_snippet"] = str(snippet)
    rec["source"] = {k: v for k, v in source.items() if v}
    rec["license"] = {k: v for k, v in license_.items() if v}
    return rec


class Importer:
    def __init__(self, args):
        self.args = args
        self.writer = CatalogWriter()
        self.validator = load_validator()
        self.mirror = None
        if getattr(args, "mirror", False):
            from storage import S3Mirror

            self.mirror = S3Mirror()
        self.rejected = 0

    def add(self, rec: dict, row_label: str) -> None:
        if self.writer.is_duplicate(rec):
            self.writer.skipped += 1
            return
        candidate = {"id": self.writer.next_id(), **rec}
        errors = validation_errors(self.validator, candidate)
        if errors:
            self.rejected += 1
            if self.rejected <= 20:
                print(f"  rejected {row_label}: {'; '.join(errors)}", file=sys.stderr)
            return
        if self.args.dry_run:
            self.writer.added += 1
            self.writer.max_id += 1
            if self.writer.added <= 3:
                print(json.dumps(candidate, ensure_ascii=False))
            return
        self.writer.append(candidate)

    def report(self) -> None:
        verb = "Would add" if self.args.dry_run else "Added"
        print(
            f"{verb} {self.writer.added} records, skipped {self.writer.skipped} duplicates, "
            f"rejected {self.rejected} invalid rows. Catalog size: "
            f"{self.writer.total + (self.writer.added if self.args.dry_run else 0)}"
        )


# --------------------------------------------------------------------------- csv


def run_csv(args) -> None:
    imp = Importer(args)
    csv_path = Path(args.csv_file)
    with csv_path.open(newline="", encoding="utf-8") as f:
        for n, row in enumerate(csv.DictReader(f), start=1):
            if args.limit and imp.writer.added >= args.limit:
                break
            label = f"row {n}"
            source = {
                "name": row.get("source_name") or args.source_name,
                "url": row.get("source_url") or args.source_url,
                "record_id": row.get("source_record_id") or None,
            }
            license_ = {
                "spdx": row.get("license") or args.license,
                "url": row.get("license_url") or args.license_url,
                "attribution": row.get("attribution") or args.attribution,
            }
            image_url = (row.get("image_url") or "").strip()
            image_path = (row.get("image_path") or "").strip()
            if imp.mirror and (image_url or image_path):
                key = source["record_id"] or f"{csv_path.stem}-{n}"
                try:
                    if image_path:
                        p = (csv_path.parent / image_path).resolve()
                        ctype = {".png": "image/png", ".webp": "image/webp"}.get(p.suffix.lower(), "image/jpeg")
                        image_url = imp.mirror.put(source["name"] or "csv", key, p.read_bytes(), ctype)
                    else:
                        image_url = imp.mirror.mirror_url(source["name"] or "csv", key, image_url)
                except Exception as exc:  # keep going on single-image failures
                    imp.rejected += 1
                    print(f"  rejected {label}: mirror failed: {exc}", file=sys.stderr)
                    continue
            elif image_path and not image_url:
                imp.rejected += 1
                print(f"  rejected {label}: image_path needs --mirror", file=sys.stderr)
                continue
            fields = {k: row.get(k) for k in TEXT_FIELDS}
            imp.add(build_record(fields, image_url, source, license_), label)
    imp.report()


# --------------------------------------------------------------------------- hugging face


def hf_license(dataset: str) -> tuple[str, str]:
    info = http_json(HF_API + urllib.parse.quote(dataset, safe="/"))
    card = info.get("cardData") or {}
    lic = card.get("license")
    if isinstance(lic, list):
        lic = lic[0] if lic else ""
    lic = (lic or "").strip().lower()
    return lic, f"https://huggingface.co/datasets/{dataset}"


def run_hf(args) -> None:
    imp = Importer(args)
    mapping = parse_pairs(args.map, "--map")
    constants = parse_pairs(args.set, "--set")

    card_license, dataset_url = hf_license(args.dataset)
    spdx = args.license or HF_LICENSE_TO_SPDX.get(card_license)
    if not spdx:
        if card_license in UNUSABLE_LICENSES:
            raise SystemExit(
                f"{args.dataset} declares license '{card_license or 'none'}'. Read its terms and, "
                "only if they allow redistribution, pass --license explicitly."
            )
        spdx = f"LicenseRef-{card_license}"
    print(f"Dataset {args.dataset}: card license '{card_license}', recording '{spdx}'")

    source_name = args.source_name or args.dataset
    license_ = {"spdx": spdx, "url": args.license_url or dataset_url, "attribution": args.attribution}

    offset = args.offset
    total = None
    while True:
        if args.limit and imp.writer.added >= args.limit:
            break
        if total is not None and offset >= total:
            break
        query = urllib.parse.urlencode(
            {"dataset": args.dataset, "config": args.config, "split": args.split,
             "offset": offset, "length": HF_PAGE}
        )
        page = http_json(f"{HF_ROWS}?{query}")
        total = page.get("num_rows_total", 0)
        rows = page.get("rows") or []
        if not rows:
            break
        for item in rows:
            if args.limit and imp.writer.added >= args.limit:
                break
            idx = item["row_idx"]
            row = item["row"]
            record_id = f"{args.config}/{args.split}/{idx}"
            label = f"row {idx}"
            source = {"name": source_name, "url": dataset_url, "record_id": record_id}
            if imp.writer.is_duplicate({"source": source}):
                imp.writer.skipped += 1
                continue

            cell = row.get(args.image_column)
            if isinstance(cell, dict) and cell.get("src"):
                # Embedded image: datasets-server returns a short-lived signed URL,
                # so it has to be copied to our own storage.
                if not imp.mirror:
                    raise SystemExit(
                        f"Column '{args.image_column}' holds embedded images whose URLs expire. "
                        "Re-run with --mirror to copy them to object storage."
                    )
                try:
                    image_url = imp.mirror.mirror_url(source_name, record_id, cell["src"])
                except Exception as exc:
                    imp.rejected += 1
                    print(f"  rejected {label}: mirror failed: {exc}", file=sys.stderr)
                    continue
            elif isinstance(cell, str) and cell:
                image_url = cell
                if args.image_url_template:
                    image_url = args.image_url_template.format(value=cell, dataset=args.dataset)
                if imp.mirror:
                    try:
                        image_url = imp.mirror.mirror_url(source_name, record_id, image_url)
                    except Exception as exc:
                        imp.rejected += 1
                        print(f"  rejected {label}: mirror failed: {exc}", file=sys.stderr)
                        continue
            else:
                imp.rejected += 1
                continue

            fields = dict(constants)
            for field, column in mapping.items():
                if row.get(column) not in (None, ""):
                    fields[field] = row[column]
            imp.add(build_record(fields, image_url, source, license_), label)
        offset += len(rows)
        time.sleep(args.sleep)
    imp.report()


# --------------------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--source-name", help="Source name recorded on every row")
    common.add_argument("--source-url", help="Source landing page")
    common.add_argument("--license", help="SPDX license id (e.g. CC-BY-4.0)")
    common.add_argument("--license-url", help="Link to the license or terms")
    common.add_argument("--attribution", help="Attribution text required by the license")
    common.add_argument("--mirror", action="store_true", help="Copy images to S3-compatible storage")
    common.add_argument("--limit", type=int, default=0, help="Stop after adding this many records")
    common.add_argument("--dry-run", action="store_true", help="Validate and preview without writing")

    sub = parser.add_subparsers(dest="command", required=True)

    p_csv = sub.add_parser("csv", parents=[common], help="Import from a CSV file")
    p_csv.add_argument("csv_file")
    p_csv.set_defaults(func=run_csv)

    p_hf = sub.add_parser("hf", parents=[common], help="Import from a Hugging Face dataset")
    p_hf.add_argument("dataset", help="owner/name on the Hugging Face Hub")
    p_hf.add_argument("--config", default="default")
    p_hf.add_argument("--split", default="train")
    p_hf.add_argument("--offset", type=int, default=0, help="First row to read")
    p_hf.add_argument("--image-column", default="image")
    p_hf.add_argument("--image-url-template", help="Build URLs from a string column, e.g. "
                      "'https://huggingface.co/datasets/{dataset}/resolve/main/{value}'")
    p_hf.add_argument("--map", action="append", default=[], metavar="FIELD=COLUMN",
                      help="Copy a dataset column into a catalog field (repeatable)")
    p_hf.add_argument("--set", action="append", default=[], metavar="FIELD=VALUE",
                      help="Set a constant value for a catalog field (repeatable)")
    p_hf.add_argument("--sleep", type=float, default=0.5, help="Pause between pages (seconds)")
    p_hf.set_defaults(func=run_hf)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
