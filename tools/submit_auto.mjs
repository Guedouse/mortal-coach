// 提交一局到 Mortal 官网，并把「真正的报告页 URL」交回给 Python。
//
// usage: node submit_auto.mjs '<json>'
//   json = {url, format, model, seat, kyokus, tempo, dry}
// 兼容旧用法: node submit_auto.mjs <paipu-url> [model]
//
// 输出约定（Python 端只认这些行，其余都是给人看的日志）：
//   SET     | ...            表单已填好，附四要素 + 实际写进输入框的 URL
//   SUBMIT_URL <url>         真正要提交的牌谱地址（排查「Mortal 拒绝」时看这行）
//   SNAP    | {json}         dry 模式：只回显字段值
//   REPORT  | <url>          成功：报告页 URL（必带非空 data 参数）
//   PAGE_ERROR <text>        Mortal 服务端渲染的错误页原文
//   RETRY   | ...            错误页属「可能只是服务端抽风」，已自动重来一轮
//   NO_PAGE / NO_TOKEN / NO_FORM / NO_REPORT_URL / REPORT_TIMEOUT / REPORT_URL
//   EXC     | ...            Runtime.evaluate 抛异常
// 退出码：0 成功或 dry 完成 / 1 无页面 / 2 无 token / 3 填表异常 / 4 未拿到报告页
const BUILD = 4;   // 与 app/main.py 的 SUBMIT_BUILD 必须一致；Python 会核对
const PORT = process.env.CDP_PORT || 9222;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
console.log('SCRIPT_BUILD', BUILD);

const argv = process.argv.slice(2);
let cfg = {};
if ((argv[0] || '').trim().startsWith('{')) {
  try { cfg = JSON.parse(argv[0]); } catch { console.log('BAD_JSON'); process.exit(1); }
} else {
  cfg = { url: argv[0] || '', model: argv[1] || '4.1b' };
}

const RAW = (cfg.url || '').trim();
const MODEL = cfg.model || '4.1b';
const SEAT = (cfg.seat === 0 || cfg.seat) ? String(cfg.seat) : '';
const KYOKUS = (cfg.kyokus || '').trim();
const TEMP = (cfg.tempo || '').trim();
const DRY = process.env.MC_DRY === '1' || !!cfg.dry;
// 设置里勾了「显示浏览器窗口」：一进来就把窗口摆到屏幕正面，让用户能自己点验证码。
// （窗口没被隐藏是前提 —— Python 那边给 Chrome 传 SW_HIDE 的话，这里搬也白搬）
const SHOW = !!cfg.show;
// 继续等待：浏览器和页面都还是上一轮那个，不要重新导航（会把挑战重建一次，
// 用户刚做的一半白费）。此时只等 token，拿到就直接接着提交。
const RESUME = !!cfg.resume;
const HOME = 'https://mjai.ekyu.moe/';

// 最多试 3 轮。实测同一个雀魂链接偶尔会被 Mortal 判成
// 「url is not from tenhou or mahjong soul」（服务端抓牌谱那一步抽风），
// 隔几秒原样重提就过了 —— 所以这类错误不能直接甩给用户。
const MAX_TRY = DRY ? 1 : 3;

// ---- 判断牌谱格式 ----
function guessFormat(u) {
  if (!u) return 'log-url';
  if (/^https?:\/\//i.test(u)) return 'log-url';
  if (/^\d+_[0-9a-f]{20,}$/i.test(u)) return 'hime-mahjong-log-id';
  if (/^\{/.test(u)) return 'tenhou6';
  if (/^[a-z0-9]{16,28}(@\d)?$/i.test(u)) return 'riichi-city-log-id';
  return 'log-url';
}
const FORMAT = (cfg.format && cfg.format !== 'auto') ? cfg.format : guessFormat(RAW);
const FIELD = {
  'log-url': 'log-url',
  'riichi-city-log-id': 'riichi-city-log-id',
  'hime-mahjong-log-id': 'hime-mahjong-log-id',
  'tenhou6': 'tenhou6',
}[FORMAT] || 'log-url';

import { isReportUrl } from './url_rules.mjs';

const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const pages = list.filter((t) => t.type === 'page');
// 优先已经停在 Mortal 的标签页；没有就用现成的空白页（gotoHome 会导过去）。
// 以前这里是「找不到 mjai 页面就直接 NO_PAGE」，而浏览器刚启动时页面可能还停在
// about:blank —— 于是连导航的机会都没有，用户只看到「没有页面」。
const page = pages.find((p) => p.url.includes('mjai.ekyu.moe')) || pages[0];
if (!page) { console.log('NO_PAGE', 'no_page_target'); process.exit(1); }
console.log('PAGE_TARGET', (page.url || '').slice(0, 80));
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 1; const pend = new Map();
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pend.has(m.id)) {
    const p = pend.get(m.id); pend.delete(m.id);
    m.error ? p.reject(new Error(JSON.stringify(m.error))) : p.resolve(m.result);
  }
};
await new Promise((r) => (ws.onopen = r));
// CDP 调用必须带超时：页面正在跳转时 Runtime.evaluate 可能永远不回，
// 没有超时整个脚本会卡死（实测卡过 10 分钟以上）。
const send = (m, p = {}, tmo = 20000) => new Promise((res, rej) => {
  const i = id++;
  const timer = setTimeout(() => {
    if (pend.has(i)) { pend.delete(i); rej(new Error('CDP_TIMEOUT ' + m)); }
  }, tmo);
  pend.set(i, {
    resolve: (v) => { clearTimeout(timer); res(v); },
    reject: (e) => { clearTimeout(timer); rej(e); },
  });
  ws.send(JSON.stringify({ id: i, method: m, params: p }));
});
const ev = async (e) => {
  try {
    const r = await send('Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true });
    return r.exceptionDetails ? 'EXC:' + JSON.stringify(r.exceptionDetails).slice(0, 300) : r.result.value;
  } catch (err) {
    return 'CDPERR:' + (err && err.message || err);
  }
};
const done = (code) => { try { ws.close(); } catch {} process.exit(code); };
const isToken = (v) => typeof v === 'string' && v.length > 50
  && !v.startsWith('CDPERR') && !v.startsWith('EXC');

// ---------------- 单轮里的四步 ----------------

// 先确保停在首页：Turnstile 只挂在首页表单上，停在报告页永远拿不到 token。
// 重试时加一个 cache-bust 参数：同一 URL 直接 navigate 会复用缓存文档，
// 连 turnstile 的 token 都还是上一轮那个（token 一次性，服务器会判 invalid captcha）。
let navSeq = 0;
async function gotoHome() {
  const url = navSeq++ ? `${HOME}?retry=${Date.now()}` : HOME;
  try {
    await send('Page.enable');
    await send('Page.navigate', { url });
  } catch (e) {
    console.log('NO_PAGE', String(e && e.message || e));
    return false;
  }
  // 「导航发出去了」不等于「页面就绪」：以前固定 sleep 4.5 秒就假定好了，
  // 网络慢或拿到空白文档时，后面每一步都在空页面上跑。这里等到真的出现表单。
  let last = null;
  for (let i = 0; i < 24; i++) {
    await sleep(600);
    last = await pageState();
    if (last && last.form) {
      console.log('AT_HOME', last.url);
      console.log('PAGE_STATE', JSON.stringify(last));
      return true;
    }
    if (last && last.ready === 'complete' && i >= 6 && !last.form && !last.widget) break;
  }
  console.log('AT_HOME', (last && last.url) || '');
  console.log('PAGE_STATE', JSON.stringify(last || {}));
  console.log('PAGE_LOAD_FAILED', JSON.stringify({
    url: (last && last.url) || '', ready: last && last.ready,
    form: !!(last && last.form), cf: !!(last && last.cf), api: last && last.api,
  }));
  return false;
}

// ---------------- 拿 Turnstile token ----------------
// 换一台机器上最常见的三种失败，日志里必须能分辨出来：
//   ① 首页压根没打开（断网 / 代理拦了）→ form=false
//   ② 首页开了但 challenges.cloudflare.com 的脚本没加载 → cf=false
//   ③ 脚本加载了，但 Cloudflare 这次要人工点「确认您是真人」→ widget=true 却迟迟没 token
// ③ 是可以自己救回来的：先把窗口挪到屏幕外时没人能点，所以脚本会
//   自动在验证框位置派发一次鼠标点击（CDP 的输入是受信任事件），
//   还不行就把窗口搬到屏幕正面，让用户自己点。

async function pageState() {
  const raw = await ev(`(()=>{
    const w = document.querySelector('.cf-turnstile, #cf-turnstile, [data-sitekey]');
    let box = null;
    try { const b = w && w.getBoundingClientRect(); if (b && b.width) {
      box = [Math.round(b.x), Math.round(b.y), Math.round(b.width), Math.round(b.height)]; } } catch (e) {}
    const els = [...document.querySelectorAll('[name="cf-turnstile-response"]')];
    // 官网首页有 review 和 bot 两套独立控件。只有 reviewForm 里那个响应用于
    // 「提交牌谱」，拿另一个表单的响应当提交凭证只会换来 invalid captcha response。
    const rf = document.forms.reviewForm;
    const rels = rf ? [...rf.querySelectorAll('[name="cf-turnstile-response"]')] : [];
    return JSON.stringify({
      url: location.href,
      title: (document.title || '').slice(0, 40),
      ready: document.readyState,
      form: !!rf,
      widget: !!w, box: box,
      token: els.length, tlen: els.map((e) => (e.value || '').length).join(','),
      rtoken: rels.length, rtlen: rels.map((e) => (e.value || '').length).join(','),
      api: typeof window.turnstile,
      cf: [...document.scripts].some((s) => (s.src || '').includes('challenges.cloudflare.com')),
      vis: document.visibilityState,
      sw: window.innerWidth, sh: window.innerHeight,
      ifr: (() => {
        const f = w && w.querySelector('iframe');
        if (!f) return null;
        const b = f.getBoundingClientRect();
        return [Math.round(b.x), Math.round(b.y), Math.round(b.width), Math.round(b.height)];
      })(),
    });
  })()`);
  try { return JSON.parse(raw); } catch { return { bad: String(raw).slice(0, 120) }; }
}

// 把验证框滚进视口。**页面用了平滑滚动，scrollIntoView 之后立刻量会读到旧坐标**
// —— 之前日志里 box 一直是 y=1194（视口才 667 高），点下去等于点空气，就是这个原因。
// 所以每滚一次都要等滚动落定再重新量，量到真的在视口里才返回。
async function bringWidgetIntoView() {
  const read = `(()=>{const d=document.querySelector('.cf-turnstile, #cf-turnstile, [data-sitekey]');
    if(!d)return '';const b=d.getBoundingClientRect();
    return JSON.stringify([b.top,b.left,b.width,b.height,innerHeight]);})()`;
  for (let i = 0; i < 5; i++) {
    const r0 = await ev(read);
    let b0; try { b0 = JSON.parse(r0); } catch { return null; }
    if (!b0) return null;
    if (b0[0] >= 0 && b0[0] + b0[3] <= b0[4]) return b0;
    const y = Math.round(b0[0] + await ev('scrollY')
                         - Math.max(80, (b0[4] - b0[3]) / 2));
    await ev(`window.scrollTo(0, ${Math.max(0, y)})`);
    await sleep(450);
    const r1 = await ev(read);
    let b1; try { b1 = JSON.parse(r1); } catch { return null; }
    if (b1 && b1[0] >= 0 && b1[0] + b1[3] <= b1[4]) return b1;
  }
  return null;
}

async function clickWidget() {
  const b = await bringWidgetIntoView();
  if (!b) return 'no_widget';
  const [, , w, h, vh] = b;
  if (b[1] + h / 2 < 0 || b[1] + h / 2 > vh) {
    return `out_of_view:${Math.round(b[0])},${Math.round(b[1])}/${vh}`;
  }
  // Turnstile 控件在 shadow DOM 里（查不到 iframe），但 300x65 的框贴在容器左上，
  // 复选框就在左边约 30px 处；再补一下正中（有时要的是整块区域）。
  const pts = [[b[1] + 30, b[0] + h / 2], [b[1] + w / 2, b[0] + h / 2]];
  for (const [x, y] of pts) {
    try {
      await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y });
      await send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', buttons: 1, clickCount: 1 });
      await sleep(90);
      await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', buttons: 0, clickCount: 1 });
    } catch (e) { return 'click_error'; }
    await sleep(500);
  }
  return `clicked@${Math.round(b[1])},${Math.round(b[0])}`;
}

// 把窗口从屏幕外搬回来，并请求聚焦（窗口是 offscreen 时没人能点验证框）
async function showWindow() {
  try {
    const w = await send('Browser.getWindowForTarget', { targetId: page.id });
    const wid = w && w.windowId;
    if (!wid) return 'no_window';
    await send('Browser.setWindowBounds', { windowId: wid, bounds: { windowState: 'normal' } });
    await send('Browser.setWindowBounds', { windowId: wid, bounds: { left: 80, top: 60, width: 1120, height: 800 } });
    await send('Page.bringToFront');
    return 'shown';
  } catch (e) {
    return 'fail:' + String((e && e.message) || e).slice(0, 60);
  }
}

// 每轮：等着 → 到点自己点一下 → 到点把窗口弹出来给人点 → 到点刷新重来
// （不要一开始就刷新，刷新会把已经等到的进度丢掉）
const usedTokens = new Set();
// 只认 reviewForm 里的响应；找不到表单时才退回全页面（此时也不会真的提交）
const readToken = () => ev(`(()=>{
  const f = document.forms.reviewForm;
  const els = f ? [...f.querySelectorAll('[name="cf-turnstile-response"]')]
                : [...document.querySelectorAll('[name="cf-turnstile-response"]')];
  for (const el of els) { if (el.value && el.value.length > 50) return el.value; }
  return '';
})()`);

// 人工等待上限（秒）。默认 5 分钟，够点一次验证；超时只是把控制权交回，
// 浏览器和页面都不关，用户可以选择「继续等待」接着等。
const MANUAL_WAIT = Math.max(60, Number(cfg.wait || 300));

async function waitToken() {
  if (SHOW) {
    // 人工模式：把窗口摆到正面、验证框滚进视野，然后**只等**。
    // 不自动点（点不对反而会把挑战弄成「正在验证…」卡死），
    // 也不定时刷新（刷新等于把用户正在做的验证重置掉）。
    console.log('WINDOW_SHOWN 0', await showWindow());
    console.log('WIDGET_IN_VIEW', JSON.stringify(await bringWidgetIntoView()));
    console.log('NEED_MANUAL', '浏览器窗口已打开：请点一下「确认您是真人」，点完会自动继续');
    console.log('VERIFICATION_REQUIRED manual');
    const t0 = Date.now();
    let nextLog = 0;
    for (let i = 0; i < MANUAL_WAIT; i++) {
      const tok = await readToken();
      if (isToken(tok) && !usedTokens.has(tok)) { usedTokens.add(tok); return tok; }
      const sec = Math.round((Date.now() - t0) / 1000);
      if (sec >= nextLog) {
        nextLog = sec + 15;
        const st = await pageState();
        console.log('TOKEN_WAIT', 0, sec + 's',
                    JSON.stringify({ form: st.form, widget: st.widget, api: st.api,
                                     cf: st.cf, rtoken: st.rtoken, rtlen: st.rtlen,
                                     vis: st.vis }));
      }
      await sleep(1000);
    }
    console.log('VERIFICATION_TIMEOUT', MANUAL_WAIT);
    return '';
  }

  // 无人值守：两轮，到点自动点一下；只有轮次之间才刷新页面
  const rounds = [{ wait: 90, click: 12, show: 40 }, { wait: 80, click: 8, show: 22 }];
  for (let round = 0; round < rounds.length; round++) {
    const t0 = Date.now();
    let clicked = false, shown = false, nextLog = 0;
    for (let i = 0; i < rounds[round].wait; i++) {
      const tok = await readToken();
      // 用过的 token 不能再交：Turnstile 一次性，复用只会换来「invalid captcha response」
      if (isToken(tok) && !usedTokens.has(tok)) { usedTokens.add(tok); return tok; }
      const sec = Math.round((Date.now() - t0) / 1000);
      if (!clicked && sec >= rounds[round].click) {
        clicked = true;
        console.log('TOKEN_CLICK', round, await clickWidget());
      }
      if (!shown && sec >= rounds[round].show) {
        shown = true;
        console.log('WINDOW_SHOWN', round, await showWindow());
        console.log('VERIFICATION_REQUIRED auto_window');
        console.log('NEED_MANUAL', '如果看到「确认您是真人」，请手动点一下');
      }
      if (sec >= nextLog) {
        nextLog = sec + 15;
        const st = await pageState();
        console.log('TOKEN_WAIT', round, sec + 's',
                    JSON.stringify({ form: st.form, widget: st.widget, api: st.api,
                                     cf: st.cf, rtoken: st.rtoken, rtlen: st.rtlen,
                                     vis: st.vis }));
      }
      await sleep(1000);
    }
    console.log('TOKEN_RETRY', round, JSON.stringify(await pageState()));
    try { await send('Page.navigate', { url: `${HOME}?retry=${Date.now()}` }); } catch (e) {}
    await sleep(6000);
  }
  return '';
}

async function fillForm() {
  return await ev(`(()=>{
    const f = document.forms.reviewForm;
    if (!f) return 'NO_FORM';
    const FMT = ${JSON.stringify(FORMAT)};
    const FIELD = ${JSON.stringify(FIELD)};
    const RAW = ${JSON.stringify(RAW)};
    document.querySelectorAll('input[name=input-method]').forEach(r=>{r.checked=(r.value===FMT);});
    try { window.changeInputMethod && window.changeInputMethod(FMT); } catch (e) {}
    if (FIELD === 'hime-mahjong-log-id' && f['hime-mahjong-region']) f['hime-mahjong-region'].value = 'china';
    if (!f[FIELD]) return 'NO_FIELD:' + FIELD;

    // 直接赋值对受控表单可能不生效：用原生 setter 写，再补 input/change 事件，
    // 让页面自己的 onchange（changeURL 会截掉 http 之前的前缀）也跑一遍。
    const setVal = (el, v) => {
      const d = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
      const dt = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value');
      const proto = el.tagName === 'TEXTAREA' ? dt : d;
      if (proto && proto.set) proto.set.call(el, v); else el.value = v;
      el.dispatchEvent(new Event('input', {bubbles: true}));
      el.dispatchEvent(new Event('change', {bubbles: true}));
    };
    setVal(f[FIELD], RAW);
    if (typeof window.changeURL === 'function' && f[FIELD].tagName === 'INPUT') {
      try { window.changeURL(f[FIELD]); } catch (e) {}
    }
    // 回读确认：字段值必须和要提交的完全一致，否则单独标出来（不然只能等服务器骂人）
    const got = f[FIELD].value;
    const warn = got === RAW ? '' : '|WARN_VALUE_MISMATCH:|' + got + '|';
    f['player-id'].value = ${JSON.stringify(SEAT)};
    f['engine'].value = 'mortal';
    f['mortal-model-tag'].value = ${JSON.stringify(MODEL)};
    if (f['kyokus']) f['kyokus'].value = ${JSON.stringify(KYOKUS)};
    if (f['temperature'] && ${JSON.stringify(TEMP)}) f['temperature'].value = ${JSON.stringify(TEMP)};
    f['ui'].value = 'killerducky';
    f['lang'].value = 'zh-CN';
    return ['ok', FMT, 'seat=' + f['player-id'].value, 'model=' + f['mortal-model-tag'].value,
            'kyokus=' + (f['kyokus'] ? f['kyokus'].value : ''), 'url=' + got].join('|') + warn;
  })()`);
}

// 提交（使用 requestSubmit，保留页面原生校验与 onsubmit 逻辑）。
//
// 这里不能只调用 btn.click()：在 CDP 的 Runtime.evaluate 中，按钮 click
// 有时只触发页面事件而没有真正发出 form 的 POST 请求，URL 会一直停在首页。
// requestSubmit() 会按 HTML 表单规范执行 constraint validation、onsubmit，
// 然后提交到 reviewForm.action（/review）。
async function fireSubmit() {
  return await ev(`(()=>{
    const f = document.forms.reviewForm;
    if (!f) return 'NO_FORM';
    const btn = f.querySelector('button[type=submit], input[type=submit]')
             || document.querySelector('button[type=submit]');
    if (typeof f.requestSubmit === 'function') {
      f.requestSubmit(btn || undefined);
      return 'requestSubmitted';
    }
    // 仅兼容极旧浏览器；现代 Chrome/WebView2 都走上面的分支。
    if (btn) { btn.click(); return 'clickedFallback'; }
    f.submit(); return 'submittedFallback';
  })()`);
}

// 等真正的报告页：每轮同时看 URL 与页面是否已渲染牌桌
async function waitReport() {
  let lastUrl = '';
  let sawProgress = false;
  let stayHome = 0;
  for (let i = 0; i < 180; i++) {
    await sleep(3000);
    const st = await ev(`JSON.stringify({u:location.href,t:document.title||'',board:!!document.querySelector('.info-round')||!!document.querySelector('.grid-main')})`);
    let o; try { o = JSON.parse(st); } catch { continue; }
    lastUrl = o.u;
    if (o.u.includes('/progress')) sawProgress = true;
    const hit = isReportUrl(o.u);
    if (hit && o.board) {
      await sleep(3000);
      return { report: hit.url, lastUrl };
    }
    if (i % 10 === 0) console.log('wait', i * 3 + 's', o.u, 'board=' + o.board);
    // 提交压根没发出去（一直停在首页）：不必等满 9 分钟，立刻交回去重来
    stayHome = (o.u === HOME || o.u === HOME.slice(0, -1) || o.u.startsWith(HOME + '?')) ? stayHome + 1 : 0;
    if (i >= 4 && stayHome >= 3) return { kind: 'NOT_SENT', lastUrl, sawProgress };
    // 新版官网把错误直接渲染成纯文本页（如「does not contain player ID」），原样带回去
    if (i >= 5 && (o.u.includes('/review') || o.u.includes('/error'))) {
      const txt = await ev('(document.body&&document.body.innerText||"").trim().slice(0,300)');
      if (txt && !o.board) return { kind: 'PAGE_ERROR', text: txt.replace(/\s+/g, ' '), lastUrl, sawProgress };
    }
  }
  return { kind: 'TIMEOUT', lastUrl, sawProgress };
}

// ---------------- 主流程（可重试） ----------------
let last = null;
for (let attempt = 1; attempt <= (RESUME ? 1 : MAX_TRY); attempt++) {
  console.log('ATTEMPT', attempt + '/' + (RESUME ? 1 : MAX_TRY));
  if (RESUME) {
    // 接续上一轮：页面还是原样，直接等 token，绝不重新导航
    console.log('RESUME', await ev('location.href'));
    console.log('PAGE_STATE', JSON.stringify(await pageState()));
  } else if (!(await gotoHome())) {
    done(1);
  }

  // 自测钩子：只验证「点验证框 / 把窗口搬回屏幕」这两个动作能不能用
  if (process.env.MC_WINDOW_TEST === '1') {
    console.log('CLICK', await clickWidget());
    console.log('SHOW', await showWindow());
    done(0);
  }

  if (!DRY) {
    const tok = await waitToken();
    if (!tok) {
      const st = await pageState();
      console.log('NO_TOKEN_STATE', JSON.stringify(st));
      console.log('NO_TOKEN len=0');
      // 人工模式下超时不是「失败」，而是「还没做完」：浏览器、profile、页面都留着，
      // Python 据此返回可恢复状态，用户点「继续等待」就在同一页面上接着等。
      if (SHOW) console.log('VERIFICATION_PENDING', 'window_kept_open');
      done(2);
    }
    console.log('TOKEN_OK len=' + tok.length);
    if (process.env.MC_TOKEN_ONLY === '1') { console.log('TOKEN_ONLY_OK'); done(0); }
  }

  console.log('URL_BEFORE_SUBMIT', await ev('location.href'));
  const setRes = await fillForm();
  console.log('SET', setRes);
  console.log('SUBMIT_URL', RAW, 'len=' + RAW.length);
  if (typeof setRes === 'string' && setRes.startsWith('EXC:')) { console.log('FORM_ERROR'); done(3); }
  if (typeof setRes === 'string' && (setRes.startsWith('NO_FORM') || setRes.startsWith('NO_FIELD'))) {
    console.log('NO_FORM', setRes); done(3);
  }

  if (DRY) {
    const snap = await ev(`(()=>{const f=document.forms.reviewForm;const o={};
      for (const k of ['log-url','riichi-city-log-id','hime-mahjong-log-id','hime-mahjong-region','player-id','engine','mortal-model-tag','kyokus','ui','lang']) {
        if (f[k]) o[k]=f[k].value;
      }
      o.__method=[...document.querySelectorAll('input[name=input-method]')].filter(r=>r.checked).map(r=>r.value).join(',');
      return JSON.stringify(o);})()`);
    console.log('SNAP', snap);
    done(0);
  }

  const clickRes = await fireSubmit();
  console.log('SUBMIT', clickRes);
  if (clickRes === 'NO_FORM' || (typeof clickRes === 'string' && clickRes.startsWith('EXC:'))) {
    console.log('FORM_ERROR', clickRes); done(3);
  }

  const res = await waitReport();
  if (res.report) { console.log('REPORT', res.report); done(0); }

  last = res;
  if (res.kind === 'PAGE_ERROR') {
    // 「does not contain player ID」是座位问题，重试没用，直接交回去让用户选座次
    const needsSeat = /player\s*id/i.test(res.text);
    if (!needsSeat && attempt < MAX_TRY) {
      console.log('RETRY', attempt, '|', res.text.slice(0, 120));
      await sleep(4000);
      continue;
    }
  } else if (res.kind === 'NOT_SENT' && attempt < MAX_TRY) {
    // 表单没发出去（还停在首页）：换一轮重来，比等 9 分钟强
    console.log('RETRY', attempt, '| submit_not_sent');
    await sleep(2000);
    continue;
  } else if (res.kind === 'TIMEOUT' && attempt < MAX_TRY && !res.sawProgress) {
    // 连 /progress 都没进去：多半是这一轮提交根本没发出去，再来一次
    console.log('RETRY', attempt, '| no progress');
    await sleep(3000);
    continue;
  }
  break;
}

if (last && last.kind === 'PAGE_ERROR') {
  console.log('PAGE_ERROR', last.text);
  console.log('REPORT_URL', last.lastUrl);
  done(4);
}
if (last && last.kind === 'NOT_SENT') {
  console.log('SUBMIT_NOT_SENT', 'still_at_home');
  console.log('REPORT_URL', last.lastUrl);
  done(4);
}
const lastUrl = (last && last.lastUrl) || '';
const hit = isReportUrl(lastUrl);
console.log('REPORT_URL', lastUrl);
console.log(hit ? 'REPORT_TIMEOUT board_not_ready' : 'NO_REPORT_URL',
            'saw_progress=' + !!(last && last.sawProgress), 'title=' + (await ev('document.title')));
done(4);
