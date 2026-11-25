import {cp, mkdir, readdir, unlink} from 'node:fs/promises';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';

const target = fileURLToPath(new URL('../../src/zombie_sim/static/', import.meta.url));
await mkdir(target, {recursive: true});
await cp(fileURLToPath(new URL('../dist/', import.meta.url)), target, {recursive: true});
const current = new Set(await readdir(fileURLToPath(new URL('../dist/assets/', import.meta.url))));
for (const name of await readdir(join(target, 'assets'))) {
  if (/^index-[\w-]+\.(js|css)$/.test(name) && !current.has(name)) {
    await unlink(join(target, 'assets', name));
  }
}
