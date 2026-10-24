// Extract API endpoints + methods from the minified bundles.
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const DIR = 'recon/assets';
const files = readdirSync(DIR).filter((f) => f.endsWith('.js'));

const API_HOSTS = ['https://api.yotoplay.com', 'https://my.yotoplay.com', 'media-secure-v2.api.yotoplay.com', 'secure-media.yotoplay.com', 'card-content.yotoplay.com', 'https://login.yotoplay.com'];

const results = [];

for (const f of files) {
  const src = readFileSync(join(DIR, f), 'utf8');

  // 1. Literal paths near API host constants
  const pathRe = /["'`](\/[a-zA-Z0-9_\-{}/.$:]+(?:\/[a-zA-Z0-9_\-{}/.$:*]+)*)["'`]/g;
  let m;
  while ((m = pathRe.exec(src))) {
    const p = m[1];
    if (!/^\/(card|content|media|user|family|account|profile|playlists|tags|library|devices|v1|oauth|authorize)/.test(p)) continue;
    results.push({ file: f, path: p });
  }

  // 2. Template-literal paths built from a host var
  const tplRe = /\$\{[A-Za-z_$][\w$]*\}\/([a-zA-Z0-9_\-{}/.$:*]+)/g;
  while ((m = tplRe.exec(src))) {
    results.push({ file: f, path: `<HOST>/${m[1]}` });
  }
}

// Dedupe
const byPath = new Map();
for (const r of results) {
  if (!byPath.has(r.path)) byPath.set(r.path, new Set());
  byPath.get(r.path).add(r.file);
}

console.log('=== API PATHS FOUND IN BUNDLES ===\n');
for (const [p, fs] of [...byPath.entries()].sort()) {
  console.log(p);
  console.log(`    ${[...fs].join(', ')}`);
}

console.log('\n=== HTTP METHOD USAGE ===\n');
const methods = {};
for (const f of files) {
  const src = readFileSync(join(DIR, f), 'utf8');
  for (const mm of src.matchAll(/\b(GET|POST|PUT|PATCH|DELETE)\b/g)) {
    methods[mm[1]] = (methods[mm[1]] || 0) + 1;
  }
}
console.log(methods);
