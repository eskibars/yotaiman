// Minimal CDP client for the logged-in Chrome instance on :9222.
// Uses Node's built-in global WebSocket (Node >= 22). No npm deps.
import { existsSync, readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

const CDP_HTTP = process.env.YOTO_CDP_HTTP || 'http://localhost:9222';

// Chrome 136+ ignores --remote-debugging-port for the default profile, and a
// browser started through chrome://inspect/#remote-debugging answers 404 on
// every /json/* path.  It still writes its browser endpoint into a
// DevToolsActivePort file in the profile directory, so that is where the
// WebSocket URL comes from when the HTTP discovery API is not there.
function userDataDirs() {
  const home = homedir();
  const dirs = [];
  if (process.env.YOTO_CHROME_USER_DATA_DIR) {
    dirs.push(process.env.YOTO_CHROME_USER_DATA_DIR);
  }
  if (process.platform === 'win32') {
    const local = process.env.LOCALAPPDATA || join(home, 'AppData', 'Local');
    dirs.push(join(local, 'Google', 'Chrome', 'User Data'));
    dirs.push(join(local, 'Chromium', 'User Data'));
  } else if (process.platform === 'darwin') {
    const support = join(home, 'Library', 'Application Support');
    dirs.push(join(support, 'Google', 'Chrome', 'User Data'));
    dirs.push(join(support, 'Chromium', 'User Data'));
  } else {
    dirs.push(join(home, '.config', 'google-chrome'));
    dirs.push(join(home, '.config', 'chromium'));
  }
  return dirs;
}

// The browser-level endpoint, as {port, wsUrl}.
export function browserEndpoint() {
  for (const dir of userDataDirs()) {
    const file = join(dir, 'DevToolsActivePort');
    try {
      if (!existsSync(file)) continue;
      const [port, path] = readFileSync(file, 'utf8').split('\n');
      if (!port || !path) continue;
      const trimmed = port.trim();
      return {
        port: Number(trimmed),
        wsUrl: `ws://127.0.0.1:${trimmed}${path.trim()}`,
      };
    } catch {
      continue;
    }
  }
  return null;
}

async function openSession(wsUrl) {
  const ws = new WebSocket(wsUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true });
    ws.addEventListener('error', () => reject(new Error(`CDP websocket failed: ${wsUrl}`)), {
      once: true,
    });
  });

  const pending = new Map();
  const listeners = new Map();
  let nextId = 1;

  ws.addEventListener('message', (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(new Error(JSON.stringify(msg.error)));
      else resolve(msg.result);
      return;
    }
    if (msg.method) {
      for (const fn of listeners.get(msg.method) || []) fn(msg.params);
    }
  });

  function send(method, params = {}) {
    const id = nextId++;
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });
  }

  function on(method, fn) {
    if (!listeners.has(method)) listeners.set(method, []);
    listeners.get(method).push(fn);
    return () => {
      const arr = listeners.get(method);
      const i = arr.indexOf(fn);
      if (i >= 0) arr.splice(i, 1);
    };
  }

  function close() {
    try { ws.close(); } catch {}
  }

  return { send, on, close };
}

// A session on the browser endpoint, for the commands that only it accepts:
// Target.createTarget, Target.getTargets, Target.closeTarget.
export async function browserSession() {
  const endpoint = browserEndpoint();
  if (!endpoint) {
    throw new Error(
      'no DevTools endpoint found: turn on chrome://inspect/#remote-debugging, ' +
        'or set YOTO_CHROME_USER_DATA_DIR to the profile directory',
    );
  }
  const session = await openSession(endpoint.wsUrl);
  return { ...session, endpoint };
}

// The page targets of the browser we are attached to.
//
// The browser endpoint is preferred over the HTTP discovery API: a browser
// started through chrome://inspect answers 404 on every /json/* path, and
// when both are available they can be different browsers.  Whatever the
// listing comes from, the other tools here create and close their tabs on
// the same browser, so the ids always refer to something that exists.
export async function listTargets() {
  const endpoint = browserEndpoint();
  if (endpoint) {
    const browser = await browserSession();
    try {
      const { targetInfos } = await browser.send('Target.getTargets');
      return targetInfos.map((t) => ({
        id: t.targetId,
        type: t.type,
        url: t.url,
        title: t.title,
        webSocketDebuggerUrl:
          `ws://127.0.0.1:${browser.endpoint.port}/devtools/page/${t.targetId}`,
      }));
    } finally {
      browser.close();
    }
  }

  const res = await fetch(`${CDP_HTTP}/json/list`);
  if (!res.ok) {
    throw new Error(
      `no DevTools endpoint: ${CDP_HTTP}/json/list returned ${res.status}. ` +
        'Turn on chrome://inspect/#remote-debugging, or set ' +
        'YOTO_CHROME_USER_DATA_DIR to the profile directory.',
    );
  }
  return res.json();
}

export async function findTarget(urlSubstring) {
  const targets = await listTargets();
  const hit = targets.find(
    (t) => t.type === 'page' && (t.url || '').includes(urlSubstring),
  );
  if (!hit) throw new Error(`no page target matching "${urlSubstring}"`);
  return hit;
}

export async function connect(urlSubstring) {
  let target;
  if (/^[0-9A-F]{12,}$/i.test(urlSubstring)) {
    // A target id was passed rather than a URL fragment.  Target.createTarget
    // hands back an upper-case id and /json/list a lower-case one, so the
    // comparison cannot be case sensitive.
    const targets = await listTargets();
    const wanted = urlSubstring.toLowerCase();
    target = targets.find((t) => String(t.id).toLowerCase() === wanted);
    if (!target) throw new Error(`no target with id "${urlSubstring}"`);
  } else {
    target = await findTarget(urlSubstring);
  }
  const session = await openSession(target.webSocketDebuggerUrl);
  return { ...session, target, targetId: target.id };
}
