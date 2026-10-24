// Capture network traffic from the Yoto page and dump API-shaped requests.
import { connect } from './cdp.mjs';
import { writeFileSync } from 'node:fs';

const SUB = process.argv[2] || 'my.yotoplay.com';
const OUT = process.argv[3] || 'recon/traffic.json';

const cdp = await connect(SUB);

const requests = [];
const responses = [];

cdp.on('Network.requestWillBeSent', (p) => {
  const { request } = p;
  requests.push({
    id: p.requestId,
    method: request.method,
    url: request.url,
    headers: request.headers,
    postData: request.postData,
    resourceType: p.type,
    initiator: p.initiator?.type,
  });
});

cdp.on('Network.responseReceived', (p) => {
  responses.push({
    id: p.requestId,
    url: p.response.url,
    status: p.response.status,
    mimeType: p.response.mimeType,
    headers: p.response.headers,
    resourceType: p.type,
  });
});

await cdp.send('Network.enable', {});
await cdp.send('Page.enable', {});
await cdp.send('Runtime.enable', {});

await cdp.send('Page.reload', { ignoreCache: false });
await new Promise((r) => setTimeout(r, 9000));

writeFileSync(OUT, JSON.stringify({ requests, responses }, null, 2));

// Summary of XHR/fetch/document traffic to the yoto API surface
const seen = new Set();
console.log('\n=== XHR / FETCH / DOCUMENT ===');
for (const r of requests) {
  if (!['XHR', 'Fetch', 'Document'].includes(r.resourceType)) continue;
  const u = new URL(r.url);
  const key = `${r.method} ${u.origin}${u.pathname}`;
  if (seen.has(key)) continue;
  seen.add(key);
  console.log(`${r.method} ${u.origin}${u.pathname}${u.search}`);
  console.log(`   type=${r.resourceType} status=${responses.find((x) => x.id === r.id)?.status ?? '?'}`);
}

console.log('\n=== ALL HOSTS ===');
const hosts = {};
for (const r of requests) {
  const h = new URL(r.url).host;
  hosts[h] = (hosts[h] || 0) + 1;
}
for (const [h, n] of Object.entries(hosts).sort((a, b) => b[1] - a[1])) {
  console.log(`${n.toString().padStart(4)}  ${h}`);
}

cdp.close();
process.exit(0);
