// 报告页 URL 判定规则（单独一个文件，方便用 node 跑单测）
// 只认两种：
//   1) pathname 是 /report 或 /report/…（Mortal 旧的报告页）
//   2) pathname 含 killerducky 且带非空的 data 参数（现在的牌桌页）
// 首页、/progress、语言首页（zh-cn.html 之类）、错误页一律不认。

export const HOST = 'mjai.ekyu.moe';

export function isReportUrl(raw) {
  let u;
  try { u = new URL(String(raw || '')); } catch { return null; }
  if (u.hostname !== HOST) return null;
  const p = u.pathname.replace(/\/+$/, '');
  const data = (u.searchParams.get('data') || '').trim();
  const isReportPath = (p === '/report' || p.startsWith('/report/'));
  const isDucky = p.toLowerCase().includes('killerducky');
  if (!isReportPath && !isDucky) return null;
  if (isDucky && !data) return null;
  return { url: u.href, path: p, data };
}
