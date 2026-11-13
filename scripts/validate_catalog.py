#!/usr/bin/env python3
"""Validate every catalog record against the schema, check id uniqueness, and
make sure no image files have been committed to the repository.

Exit code 0 when everything passes, 1 otherwise. Used by CI.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from catalog_lib import IMAGE_EXTENSIONS, REPO_ROOT, iter_records, load_validator, validation_errors  # noqa: E402

MAX_ERRORS_SHOWN = 50


def tracked_images() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return [p for p in out.splitlines() if Path(p).suffix.lower() in IMAGE_EXTENSIONS]


def main() -> int:
    validator = load_validator()
    problems: list[str] = []
    ids: set[str] = set()
    count = 0
    for path, lineno, rec in iter_records():
        count += 1
        where = f"{path.relative_to(REPO_ROOT)}:{lineno}"
        for err in validation_errors(validator, rec):
            problems.append(f"{where}: {err}")
        rid = rec.get("id")
        if rid in ids:
            problems.append(f"{where}: duplicate id {rid}")
        ids.add(rid)

    for img in tracked_images():
        problems.append(f"{img}: image files must not be committed; host them in object storage")

    for p in problems[:MAX_ERRORS_SHOWN]:
        print(p)
    if len(problems) > MAX_ERRORS_SHOWN:
        print(f"... and {len(problems) - MAX_ERRORS_SHOWN} more")
    print(f"Checked {count} records: {'OK' if not problems else f'{len(problems)} problem(s)'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
