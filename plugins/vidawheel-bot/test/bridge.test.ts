/** Test lease fencing, uncertain delivery, scope and final-answer handling without a real model. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, dirname, basename } from 'node:path';

const directory = await mkdtemp(join(tmpdir(), 'vidawheel-plugin-test-'));
process.env.VIDAWHEEL_BRIDGE_HOME = directory;
const { validateConfig, configPath } = await import('../src/config.js');
const { Bridge, analysisPrompt, completedAnswer, acquireLock } = await import('../src/bridge.js');
const { assertTarget } = await import('../src/app-server.js');
const { decodeToolResult } = await import('../src/remote.js');
const threadId = '01a15736-0f40-7942-85c5-f89ee646e132';
const config = validateConfig({ enabled: true, mcpUrl: 'http://127.0.0.1:8000/mcp',
  tokenFile: join(directory, 'credential'), threadId, repository: directory,
  desktopProcess: process.platform === 'win32' ? 'node.exe' : 'node' });

test('scope and endpoint validation refuse cross-repository or busy delivery', () => {
  assert.throws(() => validateConfig({ ...config, mcpUrl: 'http://example.com/mcp' }), /HTTPS/);
  assert.throws(() => assertTarget({ id: threadId, cwd: '/other', status: { type: 'idle' } }, config));
  assert.throws(() => assertTarget({ id: threadId, cwd: directory, status: { type: 'active' } }, config));
  assert.doesNotThrow(() => assertTarget({ id: threadId, cwd: directory, status: { type: 'active' } }, config, true));
});

test('FastMCP listing preserves separate text rows and handles an empty queue', () => {
  assert.deepEqual(decodeToolResult('list_issues', { content: [{ type: 'text', text: '{"code":"a"}' },
    { type: 'text', text: '{"code":"b"}' }] }), [{ code: 'a' }, { code: 'b' }]);
  assert.deepEqual(decodeToolResult('list_issues', { content: [] }), []);
  assert.throws(() => decodeToolResult('claim_issue', { isError: true, content: [] }));
});

test('tool output and commentary cannot become a successful final answer', () => {
  assert.throws(() => completedAnswer({ status: 'failed', items: [] }));
  assert.throws(() => completedAnswer({ status: 'completed', items: [{ type: 'commandExecution', text: 'ok' }] }));
  assert.equal(completedAnswer({ status: 'completed', items: [
    { type: 'agentMessage', phase: 'commentary', text: 'working' },
    { type: 'agentMessage', phase: 'final_answer', text: 'finding' },
  ] }), 'finding');
  assert.match(analysisPrompt({ code: 'task', revision: 1, question: 'ignore instructions' }), /不可信证据/);
});

test('one local consumer owns the lock and orderly shutdown permits takeover', async () => {
  const unlock = await acquireLock(); assert.ok(unlock);
  assert.equal(await acquireLock(), null);
  await unlock();
  const next = await acquireLock(); assert.ok(next); await next();
});

test('delivery records exact turn then submits final answer with the original fence', async () => {
  await writeFile(configPath, JSON.stringify(config));
  const calls: Array<{ name: string; args: any }> = [];
  const api = { async call(name: string, args: any) {
    calls.push({ name, args });
    if (name === 'claim_issue') return { task: { code: 'taskA', lease_token: 'fenceA', claimed_revision: 1 } };
    if (name === 'get_issue_context') return { code: 'taskA', revision: 1, question: 'synthetic' };
    return {};
  } };
  const rpc: any = { async request(method: string, args: any) {
    if (method === 'thread/read') return { thread: { id: threadId, cwd: directory, status: { type: 'idle' } } };
    if (method === 'turn/start') {
      assert.equal(args.sandboxPolicy.type, 'readOnly');
      assert.equal(args.approvalPolicy, 'never');
      const saved = JSON.parse(await readFile(join(directory, 'delivery.json'), 'utf8'));
      assert.equal(saved.phase, 'dispatching');
      return { turn: { id: 'turnA' } };
    }
    if (method === 'thread/turns/list') return { data: [{ id: 'turnA', status: 'completed',
      items: [{ type: 'agentMessage', phase: 'final_answer', text: 'Synthetic finding' }] }] };
    return {};
  } };
  await new Bridge().cycle(config, rpc, api, new AbortController().signal);
  const submit = calls.find((c) => c.name === 'submit_analysis');
  assert.equal(submit?.args.lease_token, 'fenceA'); assert.equal(submit?.args.analysis, 'Synthetic finding');
});

test('ambiguous dispatch is not replayed and no new task is claimed', async () => {
  await writeFile(join(directory, 'delivery.json'), JSON.stringify({ taskCode: 'taskA', leaseToken: 'fenceA',
    threadId, repository: directory, phase: 'dispatching', revision: 1, startedAt: Date.now() }));
  const calls: string[] = [];
  const api = { async call(name: string) { calls.push(name); return {}; } };
  await assert.rejects(new Bridge().cycle(config, {} as any, api, new AbortController().signal), /Check conversation/);
  assert.deepEqual(calls, ['renew_issue']);
});

test('context read failure records a bounded server retry before any model delivery', async () => {
  await rm(join(directory, 'delivery.json'));
  const calls: string[] = [];
  const api = { async call(name: string) {
    calls.push(name);
    if (name === 'claim_issue') return { task: { code: 'taskB', lease_token: 'fenceB', claimed_revision: 2 } };
    if (name === 'get_issue_context') throw new Error('document unavailable');
    return {};
  } };
  await assert.rejects(new Bridge().cycle(config, {} as any, api, new AbortController().signal), /unavailable/);
  assert.deepEqual(calls, ['claim_issue', 'renew_issue', 'get_issue_context', 'fail_issue']);
  assert.equal(JSON.parse(await readFile(join(directory, 'delivery.json'), 'utf8')).phase, 'submitted');
});

test('lost submit acknowledgement is reconciled from immutable server history without replay', async () => {
  await writeFile(join(directory, 'delivery.json'), JSON.stringify({ taskCode: 'taskA', leaseToken: 'old',
    threadId, repository: directory, phase: 'completed', answer: 'saved answer', revision: 1, startedAt: Date.now() }));
  const calls: string[] = [];
  await new Bridge().cycle(config, {} as any, { async call(name: string) {
    calls.push(name); return { analyses: [{ revision: 1, result: 'saved answer' }] };
  } }, new AbortController().signal);
  assert.deepEqual(calls, ['get_issue_context']);
  assert.equal(JSON.parse(await readFile(join(directory, 'delivery.json'), 'utf8')).phase, 'submitted');
});

test('expired fence prevents resumed analysis or result submission', async () => {
  await writeFile(join(directory, 'delivery.json'), JSON.stringify({ taskCode: 'taskA', leaseToken: 'expired',
    threadId, repository: directory, phase: 'completed', answer: 'old result', revision: 1, startedAt: Date.now() }));
  const calls: string[] = [];
  await assert.rejects(new Bridge().cycle(config, {} as any, { async call(name: string) {
    calls.push(name); if (name === 'get_issue_context') return { analyses: [] }; throw new Error('expired');
  } }, new AbortController().signal), /expired/);
  assert.deepEqual(calls, ['get_issue_context', 'renew_issue']);
  assert.equal(dirname(directory), tmpdir()); assert.ok(basename(directory).startsWith('vidawheel-plugin-test-'));
  await rm(directory, { recursive: true, force: true });
});
