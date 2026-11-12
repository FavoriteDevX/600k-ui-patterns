import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import fs from "fs";
import path from "path";

const server = new Server(
  { name: "open-ui-vault-mcp", version: "1.0.0" },
  { capabilities: { tools: {} } }
);

// Load catalog data
const catalogPath = path.resolve(process.cwd(), "../data/catalog.json");

server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: "search_ui_screens",
        description: "Search the 600k+ UI catalog by category, flow, platform, or tags.",
        inputSchema: {
          type: "object",
          properties: {
            query: { type: "string", description: "Keyword, flow (e.g., Onboarding), or tag" },
            category: { type: "string", description: "App category (e.g., Fintech, Education)" }
          },
          required: ["query"]
        }
      }
    ]
  };
});

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  if (request.params.name === "search_ui_screens") {
    const query = String(request.params.arguments?.query || "").toLowerCase();
    const category = String(request.params.arguments?.category || "").toLowerCase();

    const rawData = fs.readFileSync(catalogPath, "utf-8");
    const screens = JSON.parse(rawData);

    const results = screens.filter((screen: any) => {
      const matchesQuery =
        screen.flow.toLowerCase().includes(query) ||
        screen.app_name.toLowerCase().includes(query) ||
        screen.tags.some((t: string) => t.toLowerCase().includes(query));
      const matchesCategory = category ? screen.category.toLowerCase() === category : true;
      return matchesQuery && matchesCategory;
    });

    return {
      content: [
        {
          type: "text",
          text: JSON.stringify(results.slice(0, 20), null, 2)
        }
      ]
    };
  }
  throw new Error("Tool not found");
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main();
      
