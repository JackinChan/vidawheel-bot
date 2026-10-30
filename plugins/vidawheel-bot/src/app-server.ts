/** Existing-daemon JSON-RPC connection. Never starts a new app server or creates a conversation. */
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { createInterface } from 'node:readline';
import { EventEmitter } from 'node:events';
import { VERSION, type Config } from './config.js';

/** Bounded NDJSON client for the desktop's existing control socket. */
export class AppServer extends EventEmitter {
  private child?: ChildProcessWithoutNullStreams;
  private sequence = 0;
  private pending = new Map<number, { resolve: (v: any) => void; reject: (e: Error) => void }>();

  /** Attach via the CLI's existing control socket; timeout or transport errors fail closed. */
  async connect(config: Config): Promise<void> {
    const args = ['app-server', 'proxy', ...(config.socketPath ? ['--sock', config.socketPath] : [])];
    this.child = spawn(config.codexBin, args, { stdio: 'pipe', windowsHide: true });
    this.child.stderr.resume();
    const failed = () => {
      for (const entry of this.pending.values()) entry.reject(new Error('Existing Codex app-server disconnected'));
      this.pending.clear();
      this.emit('disconnected');
    };
    this.child.on('error', failed);
    this.child.on('exit', failed);
    const lines = createInterface({ input: this.child.stdout });
    lines.on('line', (line) => {
      try {
        const message = JSON.parse(line);
        if (message.method && message.id !== undefined) {
          // Unattended bridge never approves a request or executes a dynamic tool.
          this.send({ id: message.id, error: { code: -32601, message: 'Bridge does not handle approvals or tools' } });
        } else if (message.id !== undefined) {
          const entry = this.pending.get(message.id);
          this.pending.delete(message.id);
          if (message.error) entry?.reject(new Error(`Codex RPC failed: ${message.error.code}`));
          else entry?.resolve(message.result);
        } else if (message.method) this.emit('notification', message);
      } catch { this.emit('protocolError'); }
    });
    await this.request('initialize', { clientInfo: { name: 'vidawheel_bridge', version: VERSION } });
    this.send({ method: 'initialized', params: {} });
  }

  /** Send one line of JSON without shell interpolation or terminal output. */
  private send(value: unknown): void {
    if (!this.child || this.child.stdin.destroyed) throw new Error('Codex transport closed');
    this.child.stdin.write(JSON.stringify(value) + '\n');
  }

  /** Match a bounded response by numeric request ID. */
  async request(method: string, params: unknown = {}): Promise<any> {
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Codex RPC timeout: ${method}`));
      }, 15000);
      this.pending.set(id, {
        resolve: (v) => { clearTimeout(timer); resolve(v); },
        reject: (e) => { clearTimeout(timer); reject(e); },
      });
      try { this.send({ id, method, params }); }
      catch (error) { clearTimeout(timer); this.pending.delete(id); reject(error); }
    });
  }

  /** Disconnect this proxy only; never stop the desktop app-server daemon. */
  close(): void { this.child?.stdin.end(); this.child?.kill(); }
}

/** Normalize conversation scope before delivering a task into an existing chat. */
export function assertTarget(thread: any, config: Config, allowActive = false): void {
  const normalize = (path: string) => process.platform === 'win32'
    ? path.replaceAll('\\', '/').replace(/\/$/, '').toLowerCase() : path.replace(/\/$/, '');
  if (thread.id !== config.threadId || !config.repository || normalize(thread.cwd) !== normalize(config.repository)) {
    throw new Error('Conversation does not match the configured repository');
  }
  if (thread.status?.type !== 'idle' && thread.status?.type !== 'notLoaded' && !(allowActive && thread.status?.type === 'active')) {
    throw new Error('Conversation is busy or unavailable');
  }
}
