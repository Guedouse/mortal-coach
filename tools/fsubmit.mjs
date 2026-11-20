const PORT = process.env.CDP_PORT || 9222;
const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const page = list.filter(t => t.type === 'page').find(p => p.url.includes('mjai.ekyu.moe'));
if (!page) { console.log('no page'); process.exit(1); }
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 1; const pend = new Map();
ws.onmessage = ev => { const m = JSON.parse(ev.data); if (m.id && pend.has(m.id)) { const p = pend.get(m.id); pend.delete(m.id); m.error ? p.reject(new Error(JSON.stringify(m.error))) : p.resolve(m.result); } };
await new Promise(r => ws.onopen = r);
const send = (m, p = {}) => new Promise((res, rej) => { const i = id++; pend.set(i, { resolve: res, reject: rej }); ws.send(JSON.stringify({ id: i, method: m, params: p })); });
const ev = async e => { const r = await send('Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true }); return r.exceptionDetails ? 'EXC:' + JSON.stringify(r.exceptionDetails).slice(0, 300) : r.result.value; };
const sleep = ms => new Promise(r => setTimeout(r, ms));

console.log('submit ->', await ev(`(()=>{const f=document.forms.reviewForm;f.submit();return 'submitted'})()`));
for (let i = 0; i < 40; i++) {
  await sleep(3000);
  const st = await ev(`JSON.stringify({url:location.href,len:document.documentElement.outerHTML.length,txt:(document.body&&document.body.innerText||'').replace(/\\s+/g,' ').slice(0,120)})`);
  console.log(i, st);
  try { const o = JSON.parse(st); if (!o.url.includes('zh-cn.html')) { console.log('NAVIGATED'); break; } } catch {}
}
ws.close(); process.exit(0);
