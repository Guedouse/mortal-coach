// Minimal Chrome DevTools Protocol CLI (Node 22, uses global fetch + WebSocket)
// usage:
//   node cdp.js targets
//   node cdp.js nav <url> [waitMs]
//   node cdp.js eval <jsExpr>          -> prints JSON result
//   node cdp.js shot <filePath>
//   node cdp.js newpage <url>

const CDP_PORT = process.env.CDP_PORT || 9222;
const BASE = `http://127.0.0.1:${CDP_PORT}`;

async function listTargets() {
  const r = await fetch(`${BASE}/json/list`);
  return await r.json();
}

async function pickPageTarget() {
  const ts = await listTargets();
  const pages = ts.filter(t => t.type === 'page');
  if (!pages.length) throw new Error('no page target');
  // prefer a "normal" page over devtools internals
  return pages.find(p => !p.url.startsWith('devtools://')) || pages[0];
}

class CDP {
  constructor(wsUrl) { this.wsUrl = wsUrl; this.id = 0; this.pending = new Map(); }
  connect() {
    return new Promise((res, rej) => {
      this.ws = new WebSocket(this.wsUrl);
      this.ws.onopen = () => res();
      this.ws.onerror = (e) => rej(new Error('ws error'));
      this.ws.onmessage = (ev) => {
        let msg; try { msg = JSON.parse(ev.data); } catch { return; }
        if (msg.id && this.pending.has(msg.id)) {
          const { resolve, reject } = this.pending.get(msg.id);
          this.pending.delete(msg.id);
          if (msg.error) reject(new Error(JSON.stringify(msg.error)));
          else resolve(msg.result);
        }
      };
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
      const t = setTimeout(() => {
        if (this.pending.has(id)) { this.pending.delete(id); reject(new Error('timeout: ' + method)); }
      }, 60000);
      if (t.unref) t.unref();
    });
  }
  close() { try { this.ws.close(); } catch {} }
}

async function withPage(fn) {
  const t = await pickPageTarget();
  const c = new CDP(t.webSocketDebuggerUrl);
  await c.connect();
  try { return await fn(c, t); } finally { c.close(); }
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function main() {
  const [cmd, ...args] = process.argv.slice(2);
  if (cmd === 'targets') {
    const ts = await listTargets();
    console.log(JSON.stringify(ts.map(t => ({ type: t.type, url: t.url, id: t.id })), null, 1));
    return;
  }
  if (cmd === 'newpage') {
    const url = args[0] || 'about:blank';
    const r = await fetch(`${BASE}/json/new?${encodeURIComponent(url)}`, { method: 'PUT' });
    const j = await r.json();
    console.log(JSON.stringify(j));
    return;
  }
  if (cmd === 'nav') {
    const url = args[0];
    const waitMs = parseInt(args[1] || '4000', 10);
    await withPage(async (c) => {
      await c.send('Page.enable');
      await c.send('Page.navigate', { url });
      await sleep(waitMs);
      const r = await c.send('Runtime.evaluate', { expression: 'document.title + " | " + location.href', returnByValue: true });
      console.log(r.result.value);
    });
    return;
  }
  if (cmd === 'eval' || cmd === 'evalfile') {
    const expr = cmd === 'evalfile'
      ? require('fs').readFileSync(args[0], 'utf8')
      : args.join(' ');
    await withPage(async (c) => {
      const r = await c.send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
      if (r.exceptionDetails) { console.error('EXC:', JSON.stringify(r.exceptionDetails).slice(0, 1200)); process.exitCode = 2; return; }
      console.log(typeof r.result.value === 'string' ? r.result.value : JSON.stringify(r.result.value, null, 1));
    });
    return;
  }
  if (cmd === 'dump') {
    const file = args[0];
    const fs = require('fs');
    await withPage(async (c) => {
      const r = await c.send('Runtime.evaluate', { expression: 'document.documentElement.outerHTML', returnByValue: true });
      const html = r.result.value || '';
      fs.writeFileSync(file, html, 'utf8');
      console.log('dumped ' + html.length + ' chars -> ' + file);
    });
    return;
  }
  if (cmd === 'shot') {
    const file = args[0];
    const fs = require('fs');
    await withPage(async (c) => {
      const r = await c.send('Page.captureScreenshot', { format: 'png' });
      fs.writeFileSync(file, Buffer.from(r.data, 'base64'));
      console.log('saved ' + file);
    });
    return;
  }
  console.error('unknown cmd');
  process.exit(1);
}

main().then(() => process.exit(process.exitCode || 0)).catch(e => { console.error('ERR', e.message); process.exit(1); });
