// Minimal CDP client for the logged-in Chrome instance on :9222.
// Uses Node's built-in global WebSocket (Node >= 22). No npm deps.
const CDP_HTTP = 'http://localhost:9222';

export async function listTargets() {
  const res = await fetch(`${CDP_HTTP}/json/list`);
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
    // A target id was passed rather than a URL fragment.
    const targets = await listTargets();
    target = targets.find((t) => t.id === urlSubstring);
    if (!target) throw new Error(`no target with id "${urlSubstring}"`);
  } else {
    target = await findTarget(urlSubstring);
  }
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true });
    ws.addEventListener('error', () => reject(new Error('CDP websocket failed')), {
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

  return { send, on, close, target, targetId: target.id };
}
