// Screenshot a local URL using the already-running Chrome over CDP.
import { browserSession, connect } from './cdp.mjs';
import { writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const url = process.argv[2];
const out = process.argv[3] || join(tmpdir(), 'shot.png');
const width = Number(process.argv[4] || 1280);
const height = Number(process.argv[5] || 900);

// Open a fresh tab so the user's own tabs are left alone.  Chrome 136+
// answers 404 on /json/new, so the tab is created over the browser endpoint.
const browser = await browserSession();
const { targetId } = await browser.send('Target.createTarget', { url });
await new Promise((r) => setTimeout(r, 2500));

const cdp = await connect(targetId);
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

await browser.send('Target.closeTarget', { targetId });
cdp.close();
browser.close();
process.exit(0);
