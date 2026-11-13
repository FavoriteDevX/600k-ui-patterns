# 600k-ui-patterns

A searchable **catalog of real-world app and web UI screens**, organized by
category, platform and user flow, with an **MCP server** so AI agents can query
it for design references.

> **Status: early stage.** The catalog currently holds **2 sample records**.
> "600k" is the project's target, not its current size. See the
> [roadmap](#roadmap) for how the catalog is meant to grow.

---

## Why this exists

Designers and AI coding agents both need concrete references: *"show me
onboarding screens from education apps"*, *"how do fintech apps lay out a card
checkout?"*. This project keeps those references as **structured metadata**
(app, category, platform, flow, step, tags, optional code snippet) so they can
be filtered and searched instead of scrolled through.

## Design decision: metadata in git, images elsewhere

The repository stores **metadata only**. Each record points to its screenshot
through `image_url`. Images are **not** committed here, because:

- **Size.** 600,000 screenshots at 100–500 KB each is roughly 60–300 GB. GitHub
  recommends repositories stay under 1 GB and blocks files over 100 MB; a repo
  of that size would be unusable to clone.
- **Licensing.** Screenshots of third-party apps belong to their owners. Each
  image must come from a source whose license allows redistribution, and that
  license must be recorded per record.

Images should live in object storage (S3, R2, GCS) or remain hosted by the
original dataset, referenced by URL.

## Repository layout

```
data/catalog.json            The catalog (array of UI Screen records)
schemas/ui-screen.schema.json  JSON Schema for one record
scripts/import-dataset.py    Bulk import: CSV -> catalog.json
mcp-server/index.ts          MCP server exposing `search_ui_screens`
```

## Record format

Every record follows [`schemas/ui-screen.schema.json`](schemas/ui-screen.schema.json):

```json
{
  "id": "ui_000001",
  "app_name": "Stripe",
  "category": "Fintech",
  "platform": "Web",
  "flow": "Checkout",
  "step": 1,
  "tags": ["payment", "credit-card", "minimalist", "trust-badges"],
  "image_url": "https://example.com",
  "ui_code_snippet": "<div class='p-6 ...'>...</div>"
}
```

| Field             | Required | Description                                      |
| ----------------- | :------: | ------------------------------------------------ |
| `id`              | yes      | Unique id, `ui_` + 6 digits                      |
| `app_name`        | yes      | Application name                                 |
| `category`        | yes      | Industry, e.g. `Fintech`, `Education`            |
| `platform`        | yes      | `iOS`, `Android` or `Web`                        |
| `flow`            | yes      | User flow, e.g. `Onboarding`, `Checkout`         |
| `step`            | no       | Position of the screen inside the flow           |
| `tags`            | no       | Free-form descriptive tags                       |
| `image_url`       | yes      | URL of the screenshot                            |
| `ui_code_snippet` | no       | Optional HTML/Tailwind or React approximation    |

## Adding screens in bulk

1. Create `scripts/raw_screens.csv` with the columns
   `app_name,category,platform,flow,step,tags,image_url,ui_code_snippet`
   (`tags` is a comma-separated list inside a quoted field).
2. Run the importer from the `scripts` folder:

```bash
cd scripts
```

```bash
python import-dataset.py
```

New records are appended to `data/catalog.json` with sequential ids.

## Using the MCP server

The server exposes one tool, `search_ui_screens`:

| Argument   | Type   | Description                                         |
| ---------- | ------ | --------------------------------------------------- |
| `query`    | string | Matches app name, flow or tags (case-insensitive)   |
| `category` | string | Optional exact category filter                      |

It returns up to 20 matching records as JSON. Install the SDK and run it from
the `mcp-server` folder (the catalog path is resolved relative to it):

```bash
cd mcp-server
```

```bash
npm install @modelcontextprotocol/sdk tsx
```

```bash
npx tsx index.ts
```

Example MCP client configuration:

```json
{
  "mcpServers": {
    "ui-patterns": {
      "command": "npx",
      "args": ["tsx", "index.ts"],
      "cwd": "/path/to/600k-ui-patterns/mcp-server"
    }
  }
}
```

## Roadmap

- [ ] Add `source` and `license` fields to the schema, required for every record
- [ ] Import metadata from openly licensed research datasets of UI screenshots
      (check each dataset's license terms before importing)
- [ ] Split the catalog into sharded JSONL files once it passes ~50k records
- [ ] Replace the linear scan in the MCP server with an index (SQLite FTS)
- [ ] Add filters for `platform` and `flow`, plus pagination

## Contributing

Pull requests that add records are welcome if each screenshot's source allows
redistribution and the record states where it came from. Do not commit image
files to this repository.

## License

No license has been chosen yet. Until one is added, all rights are reserved by
the repository owner. Screenshots referenced by the catalog remain the property
of their respective owners.
