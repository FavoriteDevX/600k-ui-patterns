import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

type Screen = {
  id: string;
  app_name: string;
  category: string;
  platform: string;
  flow: string;
  step?: number;
  tags?: string[];
  image_url: string;
  ui_code_snippet?: string;
  source: { name: string; url: string; record_id?: string };
  license: { spdx: string; url?: string; attribution?: string };
};

const here = path.dirname(fileURLToPath(import.meta.url));
const catalogDir = process.env.CATALOG_DIR ?? path.resolve(here, "../data/catalog");

// Load all JSONL shards once at startup. Images are not stored here: each
// record only carries image_url plus its source and license.
function loadCatalog(): Screen[] {
  if (!fs.existsSync(catalogDir)) return [];
  const screens: Screen[] = [];
  const shards = fs.readdirSync(catalogDir).filter((f) => /^part-\d{5}\.jsonl$/.test(f)).sort();
  for (const shard of shards) {
    const lines = fs.readFileSync(path.join(catalogDir, shard), "utf-8").split("\n");
    for (const line of lines) {
      if (line.trim()) screens.push(JSON.parse(line));
    }
  }
  return screens;
}

const screens = loadCatalog();

const server = new Server(
  { name: "ui-patterns-mcp", version: "1.1.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "search_ui_screens",
      description: `Search the UI screen catalog (${screens.length} records) by keyword, category, platform or flow. Each result includes image_url, source and license.`,
      inputSchema: {
        type: "object",
        properties: {
          query: { type: "string", description: "Keyword matched against app name, flow and tags" },
          category: { type: "string", description: "Exact category, e.g. Fintech, Education" },
          platform: { type: "string", enum: ["iOS", "Android", "Web", "Desktop"] },
          flow: { type: "string", description: "Exact flow, e.g. Onboarding, Checkout" },
          limit: { type: "integer", minimum: 1, maximum: 100, default: 20 },
          offset: { type: "integer", minimum: 0, default: 0 }
        },
        required: ["query"]
      }
    }
  ]
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  if (request.params.name !== "search_ui_screens") {
    throw new Error("Tool not found");
  }
  const args = request.params.arguments ?? {};
  const query = String(args.query ?? "").toLowerCase();
  const category = String(args.category ?? "").toLowerCase();
  const platform = String(args.platform ?? "").toLowerCase();
  const flow = String(args.flow ?? "").toLowerCase();
  const limit = Math.min(Math.max(Number(args.limit ?? 20), 1), 100);
  const offset = Math.max(Number(args.offset ?? 0), 0);

  const matches = screens.filter((s) => {
    const matchesQuery =
      !query ||
      s.app_name.toLowerCase().includes(query) ||
      s.flow.toLowerCase().includes(query) ||
      (s.tags ?? []).some((t) => t.toLowerCase().includes(query));
    return (
      matchesQuery &&
      (!category || s.category.toLowerCase() === category) &&
      (!platform || s.platform.toLowerCase() === platform) &&
      (!flow || s.flow.toLowerCase() === flow)
    );
  });

  return {
    content: [
      {
        type: "text",
        text: JSON.stringify(
          { total: matches.length, offset, results: matches.slice(offset, offset + limit) },
          null,
          2
        )
      }
    ]
  };
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main();
