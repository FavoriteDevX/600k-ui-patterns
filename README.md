# 600k-ui-patterns

A searchable **catalog of real-world app and web UI screens** (mobile, web and
desktop), organized by category, platform and user flow, with an **MCP server**
so AI agents can query it for design references.

> **Status: early stage.** The catalog is empty and ready for its first import.
> "600k" is the project's target, not its current size. Run
> `python scripts/validate_catalog.py` to see the real count.

---

## How it works: metadata in git, images in object storage

```
 dataset / your captures ──► scripts/import_dataset.py ──► data/catalog/part-*.jsonl  (git)
                                       │
                                       └── --mirror ──► S3 / R2 / B2 bucket        (images)
                                                          ▲
                              record.image_url ───────────┘
```

- The repository stores **metadata only**: one JSON record per line, sharded
  into files of 50,000 records (`data/catalog/part-00000.jsonl`, ...).
- **Images are never committed.** Each record points to its screenshot with an
  HTTPS `image_url`, either on the original host or in your own S3-compatible
  bucket. `.gitignore` blocks image files and CI fails if one gets through.
- **Every record has a `source` and a `license`.** The importer rejects rows
  without them, so you can always trace where a screenshot came from and under
  which terms it can be redistributed.

Why: 600,000 screenshots at 100–500 KB each is roughly 60–300 GB. GitHub
recommends repositories stay under 1 GB, while the metadata for 600k screens is
around 300–500 MB of text.

## Repository layout

```
data/catalog/part-*.jsonl        The catalog (sharded JSONL, metadata only)
data/examples/                   Old placeholder records, not part of the catalog
schemas/ui-screen.schema.json    JSON Schema for one record
scripts/import_dataset.py        Bulk importer (CSV or Hugging Face datasets)
scripts/storage.py               Image mirroring to S3-compatible storage
scripts/validate_catalog.py      Schema, id and "no images in git" checks
scripts/example.csv              CSV template for the importer
mcp-server/index.ts              MCP server exposing `search_ui_screens`
.github/workflows/               CI that runs the validator on every push
```

## Record format

Every record follows [`schemas/ui-screen.schema.json`](schemas/ui-screen.schema.json):

```json
{
  "id": "ui_000001",
  "app_name": "Example App",
  "category": "Productivity",
  "platform": "Desktop",
  "flow": "Settings",
  "step": 1,
  "tags": ["settings", "sidebar", "dark-mode"],
  "image_url": "https://cdn.example.com/screens/example-settings.png",
  "source": { "name": "My captures", "url": "https://example.com", "record_id": "capture-0001" },
  "license": { "spdx": "CC-BY-4.0", "url": "https://creativecommons.org/licenses/by/4.0/", "attribution": "Screenshot by Example Team" }
}
```

| Field               | Required | Description                                            |
| ------------------- | :------: | ------------------------------------------------------ |
| `id`                | yes      | `ui_` + 6+ digits, assigned by the importer            |
| `app_name`          | yes      | Application name                                       |
| `category`          | yes      | Industry, e.g. `Fintech`, `Education`                  |
| `platform`          | yes      | `iOS`, `Android`, `Web` or `Desktop`                   |
| `flow`              | yes      | User flow, e.g. `Onboarding`, `Checkout`               |
| `step`              | no       | Position of the screen inside the flow                 |
| `tags`              | no       | Free-form descriptive tags                             |
| `image_url`         | yes      | Public **HTTPS** URL of the screenshot                 |
| `ui_code_snippet`   | no       | Optional HTML/Tailwind or React approximation          |
| `source.name`       | yes      | Dataset or origin name                                 |
| `source.url`        | yes      | Landing page of the dataset or origin                  |
| `source.record_id`  | no       | Id inside the source; used to skip duplicates          |
| `license.spdx`      | yes      | SPDX id (`CC-BY-4.0`, `MIT`...) or `LicenseRef-*`      |
| `license.url`       | no       | Link to the license or terms                           |
| `license.attribution` | no     | Attribution text the license requires                  |

## Importing screens

Install the Python dependencies (`boto3` is only needed for `--mirror`):

```bash
pip install -r scripts/requirements.txt
```

Every import validates each record against the schema, assigns sequential
ids, skips rows already imported (same `source.name` + `source.record_id`),
and reports how many were added, skipped and rejected. Add `--dry-run` to
preview without writing, and `--limit N` to import in batches.

### From a CSV

Copy [`scripts/example.csv`](scripts/example.csv). Columns:
`app_name, category, platform, flow, step, tags, image_url, ui_code_snippet,
source_name, source_url, source_record_id, license, license_url, attribution`,
plus an optional `image_path` (a local file, uploaded when you pass `--mirror`).
Source and license can also be given once on the command line:

```bash
python scripts/import_dataset.py csv my-screens.csv --source-name "My captures" --source-url https://example.com --license CC-BY-4.0
```

### From a Hugging Face dataset

The importer reads rows through the public datasets-server API and takes the
license from the dataset card. It **refuses** datasets whose card says
`other`, `unknown` or nothing, unless you read the terms yourself and pass
`--license`.

```bash
python scripts/import_dataset.py hf OWNER/DATASET --config default --split train --image-column image --map ui_code_snippet=text --set app_name="Dataset name" --set category=Landing --set platform=Web --set flow=Landing --mirror --limit 5000
```

- `--map FIELD=COLUMN` copies a dataset column into a catalog field.
- `--set FIELD=VALUE` sets a fixed value for every row.
- Images embedded in the dataset get short-lived URLs from the API, so they
  **require `--mirror`**. If the image column holds file paths or URLs instead,
  use `--image-url-template` to build stable links without mirroring.
- Re-running the same command resumes where it stopped, because duplicates
  are skipped. `--offset` jumps ahead directly.

### Mirroring images to object storage

`--mirror` downloads each image and uploads it to any S3-compatible bucket
(AWS S3, Cloudflare R2, Backblaze B2, MinIO), then writes the public URL into
`image_url`. Configure it with environment variables:

| Variable                | Description                                          |
| ----------------------- | ---------------------------------------------------- |
| `S3_BUCKET`             | Bucket name (required)                               |
| `S3_PUBLIC_BASE_URL`    | Public HTTPS base that serves the bucket (required)  |
| `S3_ENDPOINT_URL`       | Endpoint for non-AWS providers, e.g. R2              |
| `S3_PREFIX`             | Key prefix, default `screens`                        |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` | Credentials       |

Objects are stored as `screens/<source>/<record_id>.<ext>`. Keep credentials
in your shell or a local `.env` (ignored by git), never in the repository.

## Validating

```bash
python scripts/validate_catalog.py
```

Checks every record against the schema, makes sure ids are unique, and fails
if any image file is tracked by git. CI runs the same check on every push.

## Using the MCP server

The server loads every shard in `data/catalog/` at startup (override with
`CATALOG_DIR`) and exposes one tool, `search_ui_screens`:

| Argument   | Type    | Description                                        |
| ---------- | ------- | -------------------------------------------------- |
| `query`    | string  | Matches app name, flow or tags (case-insensitive)  |
| `category` | string  | Optional exact category                            |
| `platform` | string  | Optional: `iOS`, `Android`, `Web`, `Desktop`       |
| `flow`     | string  | Optional exact flow                                |
| `limit`    | integer | Results per page, 1–100 (default 20)               |
| `offset`   | integer | Pagination offset (default 0)                      |

It returns `{ total, offset, results }`, and each result carries its
`image_url`, `source` and `license`.

```bash
cd mcp-server
```

```bash
npm install
```

```bash
npm start
```

Example MCP client configuration:

```json
{
  "mcpServers": {
    "ui-patterns": {
      "command": "npx",
      "args": ["tsx", "/path/to/600k-ui-patterns/mcp-server/index.ts"]
    }
  }
}
```

## Roadmap

- [x] `source` and `license` required on every record
- [x] Bulk importer for CSV and Hugging Face datasets, with de-duplication
- [x] Image mirroring to S3-compatible storage
- [x] Sharded JSONL catalog, validator and CI
- [x] MCP filters for platform and flow, plus pagination
- [ ] First real import from an openly licensed UI screenshot dataset
- [ ] Replace the in-memory scan in the MCP server with an index (SQLite FTS)
      once the catalog passes ~100k records

## Contributing

Pull requests that add records are welcome when each screenshot's source
allows redistribution and the record states its source and license. Do not
commit image files; `python scripts/validate_catalog.py` must pass.

## License

No license has been chosen yet for the code and metadata. Until one is added,
all rights are reserved by the repository owner. Screenshots referenced by the
catalog remain the property of their respective owners and are governed by the
license recorded on each record.
