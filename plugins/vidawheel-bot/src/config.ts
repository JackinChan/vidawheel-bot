/** Personal connection configuration; credentials and runtime journals never live in the plugin cache. */
import { homedir } from 'node:os';
import { join, isAbsolute } from 'node:path';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { z } from 'zod';

export const configSchema = z.object({
  enabled: z.boolean().default(false),
  mcpUrl: z.string().url(),
  tokenFile: z.string().refine(isAbsolute, 'Use an absolute credential file path'),
  codexBin: z.string().min(1).default('codex'),
  socketPath: z.string().optional(),
  threadId: z.string().uuid().optional(),
  repository: z.string().refine(isAbsolute, 'Use an absolute repository path').optional(),
  desktopProcess: z.string().min(1).optional(),
  pollSeconds: z.number().int().min(5).max(60).default(10),
  analysisTimeoutSeconds: z.number().int().min(30).max(1800).default(600),
}).strict();
export type Config = z.infer<typeof configSchema>;
export const VERSION = '0.1.1';
export const dataDir = process.env.VIDAWHEEL_BRIDGE_HOME || join(homedir(), '.vidawheel-bot');
export const configPath = join(dataDir, 'config.json');

/** Atomically replace personal state with owner-only permissions on POSIX. */
export async function saveJson(path: string, value: unknown): Promise<void> {
  await mkdir(dataDir, { recursive: true, mode: 0o700 });
  const temporary = `${path}.${process.pid}.tmp`;
  await writeFile(temporary, JSON.stringify(value, null, 2) + '\n', { mode: 0o600 });
  await rename(temporary, path);
}

/** Validate the endpoint; only loopback development connections may use plain HTTP. */
export function validateConfig(value: unknown): Config {
  const config = configSchema.parse(value);
  const url = new URL(config.mcpUrl);
  if (url.username || url.password || url.hash || !['http:', 'https:'].includes(url.protocol)) {
    throw new Error('Invalid MCP endpoint');
  }
  if (url.protocol !== 'https:' && !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)) {
    throw new Error('Remote MCP requires HTTPS');
  }
  return config;
}

/** Load fresh settings on every polling cycle so pause and rebind take effect. */
export async function loadConfig(): Promise<Config> {
  return validateConfig(JSON.parse(await readFile(configPath, 'utf8')));
}
