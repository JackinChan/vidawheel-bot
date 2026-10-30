/** Plugin stdio entrypoint and local diagnostics; stdout is reserved for MCP while serving. */
import { readFile, stat, rename } from 'node:fs/promises';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';
import { AppServer, assertTarget } from './app-server.js';
import { Bridge, desktopRunning } from './bridge.js';
import { configPath, dataDir, loadConfig, saveJson, validateConfig, VERSION } from './config.js';
import { Remote } from './remote.js';

/** A short-lived diagnostic connection never creates threads or starts a daemon. */
async function withApp<T>(run: (app: AppServer) => Promise<T>): Promise<T> {
  const app = new AppServer();
  try { await app.connect(await loadConfig()); return await run(app); }
  finally { app.close(); }
}

/** Verify both transports and exact conversation scope without claiming a task. */
export async function doctor(): Promise<unknown> {
  const config = await loadConfig();
  const desktop = await desktopRunning(config);
  if (!desktop) return { ready: false, desktop: false, reason: 'Configured desktop process is not running' };
  return withApp(async (app) => {
    let targetReady = false;
    if (config.threadId && config.repository) {
      const { thread } = await app.request('thread/read', { threadId: config.threadId });
      assertTarget(thread, config, true); targetReady = true;
    }
    const remote = new Remote();
    try { await remote.connect(config); await remote.call('list_issues', { limit: 1 }); }
    finally { await remote.close(); }
    return { ready: targetReady, desktop, existingAppServer: true, remoteMcp: true, enabled: config.enabled };
  });
}

/** Register local-only controls. Credentials are read from disk, never accepted as tool arguments. */
export async function serve(): Promise<void> {
  const server = new McpServer({ name: 'vidawheel-bridge', version: VERSION });
  const bridge = new Bridge();
  const result = (value: unknown) => ({ content: [{ type: 'text' as const, text: JSON.stringify(value) }] });
  server.registerTool('bridge_status', { description: 'Inspect local connection status without returning credentials.' }, async () => {
    let state: unknown = { state: 'not_started' };
    try { state = JSON.parse(await readFile(join(dataDir, 'status.json'), 'utf8')); } catch { /* Not configured yet. */ }
    return result({ state, configPath });
  });
  server.registerTool('bridge_doctor', { description: 'Check desktop, existing app-server, target and remote MCP without claiming work.' },
    async () => result(await doctor()));
  server.registerTool('bridge_chats', {
    description: 'Page through chats on the existing local app-server; creates no chats.',
    inputSchema: { cursor: z.string().optional() },
  }, async ({ cursor }) => result(await withApp((app) => app.request('thread/list', {
    limit: 25, cursor, sourceKinds: ['cli', 'vscode', 'appServer', 'exec'], sortKey: 'updated_at',
  }))));
  server.registerTool('bridge_bind', {
    description: 'Bind the user-selected existing idle chat to its absolute repository; pauses receiving.',
    inputSchema: { threadId: z.string().uuid(), repository: z.string().min(1) },
  }, async ({ threadId, repository }) => {
    await assertNoDelivery();
    const config = validateConfig({ ...await loadConfig(), threadId, repository, enabled: false });
    if (!(await stat(repository)).isDirectory()) throw new Error('Repository directory does not exist');
    await withApp(async (app) => { const { thread } = await app.request('thread/read', { threadId }); assertTarget(thread, config); });
    await saveJson(configPath, config);
    return result({ bound: true, threadId, repository, enabled: false });
  });
  server.registerTool('bridge_enable', {
    description: 'Enable receiving only after explicit user request and successful diagnostics, or pause it.',
    inputSchema: { enabled: z.boolean() },
  }, async ({ enabled }) => {
    const config = await loadConfig();
    if (enabled) {
      const check = await doctor() as any;
      if (!check.ready) throw new Error('Desktop bridge is not ready');
    }
    await saveJson(configPath, { ...config, enabled });
    return result({ enabled });
  });
  server.registerTool('bridge_recover', {
    description: 'Recover an ambiguous delivery using an existing turn ID selected after inspecting chat history; never replays the prompt.',
    inputSchema: { turnId: z.string().min(1) },
  }, async ({ turnId }) => {
    const config = await loadConfig();
    if (config.enabled) throw new Error('Pause receiving before recovery');
    const journal = JSON.parse(await readFile(join(dataDir, 'delivery.json'), 'utf8'));
    if (journal.phase !== 'dispatching' || journal.threadId !== config.threadId) throw new Error('No matching ambiguous delivery');
    const turns = await withApp((app) => app.request('thread/turns/list', {
      threadId: journal.threadId, limit: 100, sortDirection: 'desc', itemsView: 'full',
    }));
    const turn = (turns.data || turns.turns || []).find((t: any) => t.id === turnId);
    const marker = `[VidaWheel task ${journal.taskCode} revision ${journal.revision}]`;
    if (!turn || !(turn.items || []).some((i: any) => i.type === 'userMessage' && JSON.stringify(i).includes(marker))) {
      throw new Error('Turn does not contain the exact task/revision marker');
    }
    await saveJson(join(dataDir, 'delivery.json'), { ...journal, phase: 'running', turnId });
    return result({ recovered: true, turnId });
  });
  server.registerTool('bridge_clear_delivery', {
    description: 'After explicit user review, archive a delivery with no active server lease or model turn. Pause first; ambiguous dispatch must be recovered first.',
    inputSchema: { taskCode: z.string().min(1) },
  }, async ({ taskCode }) => {
    const config = await loadConfig();
    if (config.enabled) throw new Error('Pause receiving first');
    const path = join(dataDir, 'delivery.json');
    const journal = JSON.parse(await readFile(path, 'utf8'));
    if (journal.taskCode !== taskCode || journal.phase === 'dispatching') throw new Error('Delivery mismatch or unresolved dispatch');
    const remote = new Remote();
    try {
      await remote.connect(config);
      const task = await remote.call('get_issue_context', { task_code: taskCode, include_document: false });
      if (task.status === 'running') throw new Error('Server task still has an active owner');
    } finally { await remote.close(); }
    if (journal.turnId) {
      await withApp(async (app) => {
        const turns = await app.request('thread/turns/list', { threadId: journal.threadId, limit: 100, itemsView: 'full' });
        const turn = turns.data.find((t: any) => t.id === journal.turnId);
        if (!turn || turn.status === 'inProgress') throw new Error('Cannot confirm that the model turn has stopped');
      });
    }
    await rename(path, join(dataDir, `delivery-resolved-${Date.now()}.json`));
    return result({ archived: true, taskCode });
  });
  const transport = new StdioServerTransport();
  server.server.onclose = () => bridge.stop();
  process.stdin.on('end', () => { bridge.stop(); void server.close(); });
  process.on('SIGTERM', () => { bridge.stop(); void server.close(); });
  process.on('SIGINT', () => { bridge.stop(); void server.close(); });
  await server.connect(transport);
  void bridge.run().catch(() => { console.error('VidaWheel consumer stopped; inspect local status.'); });
}

/** Refuse scope changes while a task still has unresolved delivery state. */
async function assertNoDelivery(): Promise<void> {
  try {
    const journal = JSON.parse(await readFile(join(dataDir, 'delivery.json'), 'utf8'));
    if (journal.phase !== 'submitted') throw new Error('Resolve current delivery before rebinding');
  } catch (error: any) { if (error.code !== 'ENOENT') throw error; }
}

/** CLI setup persists only paths/settings; the user creates the separate credential file. */
async function main(): Promise<void> {
  const command = process.argv[2];
  if (command === 'serve') return serve();
  if (command === 'doctor') { console.log(JSON.stringify(await doctor(), null, 2)); return; }
  if (command === 'setup') {
    const [mcpUrl, tokenFile] = process.argv.slice(3);
    try { await stat(configPath); throw new Error('Configuration already exists; edit it instead of overwriting'); }
    catch (error: any) { if (error.code !== 'ENOENT') throw error; }
    const config = validateConfig({ mcpUrl, tokenFile });
    await saveJson(configPath, config); console.log(`Configuration created (paused): ${configPath}`); return;
  }
  throw new Error('Usage: node dist/bridge.mjs serve|doctor|setup <MCP_URL> <ABSOLUTE_TOKEN_FILE>');
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(() => { console.error('VidaWheel bridge failed. Check configuration, existing Codex service and local status.'); process.exitCode = 1; });
}
