// Screenshot a local URL using the already-running Chrome over CDP.
import { connect, listTargets } from './cdp.mjs';
import { writeFileSync } from 'node:fs';

const url = process.argv[2];
const out = process.argv[3] || '/tmp/shot.png';
const width = Number(process.argv[4] || 1280);
const height = Number(process.argv[5] || 900);

// Open a fresh tab so the user's own tabs are left alone.
const res = await fetch(
  `http://localhost:9222/json/new?${encodeURIComponent(url)}`,
  { method: 'PUT' },
);
const target = await res.json();
await new Promise((r) => setTimeout(r, 2500));

const cdp = await connect(target.id);
await cdp.send('Emulation.setDeviceMetricsOverride', {
  width,
  height,
  deviceScaleFactor: 2,
  mobile: false,
});
await new Promise((r) => setTimeout(r, 700));

const shot = await cdp.send('Page.captureScreenshot', {
  format: 'png',
  captureBeyondViewport: true,
});
writeFileSync(out, Buffer.from(shot.data, 'base64'));
console.log(`wrote ${out}`);

await fetch(`http://localhost:9222/json/close/${target.id}`);
cdp.close();
process.exit(0);
