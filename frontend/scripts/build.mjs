import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';

// Windows security scanners can keep esbuild's AppData temp directory locked
// during Vite's final chunk transform. Keep build-owned temporary files inside
// the repository's ignored work directory instead.
const tempDirectory = join(process.cwd(), 'work', 'esbuild-tmp');
mkdirSync(tempDirectory, { recursive: true });
process.env.TEMP = tempDirectory;
process.env.TMP = tempDirectory;
process.env.TMPDIR = tempDirectory;

const viteCli = join(process.cwd(), 'node_modules', 'vite', 'bin', 'vite.js');
const result = spawnSync(process.execPath, [viteCli, 'build'], {
    stdio: 'inherit',
    env: process.env,
});

process.exitCode = result.status ?? 1;
