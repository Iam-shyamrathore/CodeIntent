/** Shapes of the MCP token endpoints; safe to import from client and server components. */
export type McpToken = {
  id: string;
  hint: string;
  created_at: string;
  last_used_at: string | null;
};
export type NewMcpToken = McpToken & { token: string; endpoint: string };
