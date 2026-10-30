/** Authenticated client for the existing task MCP server; server owns bot grants and fencing. */
import { readFile } from 'node:fs/promises';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import { VERSION, type Config } from './config.js';

export interface TaskApi { call(name: string, args?: Record<string, unknown>): Promise<any> }

/** FastMCP list results arrive as one text content block per row, not one JSON array. */
export function decodeToolResult(name: string, result: any): any {
  if (result.isError) throw new Error(`Task MCP operation failed: ${name}`);
  const values = result.content.filter((c: any) => c.type === 'text').map((c: any) => JSON.parse(c.text));
  if (name === 'list_issues') return values.length === 1 && Array.isArray(values[0]) ? values[0] : values;
  if (values.length !== 1) throw new Error('Missing or ambiguous MCP result');
  return values[0];
}

/** Employee-scoped task connection; grants remain entirely server-controlled. */
export class Remote implements TaskApi {
  private client = new Client({ name: 'vidawheel-desktop-bridge', version: VERSION });

  /** Read personal credential without exposing it to the model or child app-server process. */
  async connect(config: Config): Promise<void> {
    const token = (await readFile(config.tokenFile, 'utf8')).trim();
    if (!token || /\s/.test(token)) throw new Error('Invalid personal credential file');
    await this.client.connect(new StreamableHTTPClientTransport(new URL(config.mcpUrl), {
      requestInit: { headers: { Authorization: `Bearer ${token}` } },
    }), { timeout: 15000 });
  }

  /** Parse standard tool results and keep remote error content out of process logs. */
  async call(name: string, args: Record<string, unknown> = {}): Promise<any> {
    const result = await this.client.callTool({ name, arguments: args }, undefined, { timeout: 45000 });
    return decodeToolResult(name, result);
  }

  /** End only this employee connection. */
  async close(): Promise<void> { await this.client.close(); }
}
