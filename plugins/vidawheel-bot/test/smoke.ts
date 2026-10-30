/** Verify the distributable over real stdio MCP and optionally the running Docker HTTP MCP. */
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve, dirname, basename } from 'node:path';
import assert from 'node:assert/strict';
import { setTimeout as delay } from 'node:timers/promises';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

const home = await mkdtemp(join(tmpdir(), 'vidawheel-smoke-'));
const bundle = resolve(process.argv[2] || 'dist/bridge.mjs');
const env = Object.fromEntries(Object.entries(process.env).filter((entry): entry is [string, string] => entry[1] !== undefined));
const client = new Client({ name: 'plugin-acceptance', version: '1.0.0' });
try {
  const transport = new StdioClientTransport({ command: process.execPath, args: [bundle, 'serve'],
    env: { ...env, VIDAWHEEL_BRIDGE_HOME: home }, stderr: 'pipe' });
  await client.connect(transport);
  const tools = await client.listTools();
  assert.equal(tools.tools.length, 7);
  const result = await client.callTool({ name: 'bridge_status', arguments: {} });
  assert.ok(!result.isError);
  await client.close();
  await delay(300);
  const status = JSON.parse(await readFile(join(home, 'status.json'), 'utf8'));
  assert.equal(status.state, 'stopped');
  console.log('Installed bundle: stdio initialization, 7 tools, status and transport shutdown passed.');
  if (process.env.MCP_EMPLOYEE_ONE) {
    process.env.VIDAWHEEL_BRIDGE_HOME = home;
    const { Remote } = await import('../src/remote.js');
    const { validateConfig } = await import('../src/config.js');
    const tokenFile = join(home, 'credential');
    await writeFile(tokenFile, process.env.MCP_EMPLOYEE_ONE, { mode: 0o600 });
    const remote = new Remote();
    try {
      await remote.connect(validateConfig({ mcpUrl: process.env.SMOKE_MCP_URL || 'http://127.0.0.1:8000/mcp', tokenFile }));
      const issues = await remote.call('list_issues', { limit: 5 });
      assert.ok(Array.isArray(issues));
      if (issues.length) {
        const context = await remote.call('get_issue_context', { task_code: issues[0].code, include_document: false });
        assert.equal(context.code, issues[0].code);
      }
      console.log('Docker HTTP MCP: authenticated listing/context passed; no task claimed or completed.');
    } finally { await remote.close(); }
  }
} finally {
  await client.close().catch(() => {});
  assert.equal(dirname(home), tmpdir()); assert.ok(basename(home).startsWith('vidawheel-smoke-'));
  await rm(home, { recursive: true, force: true });
}
