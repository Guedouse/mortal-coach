// 报告页判定的单测：node tools/test_rules.mjs
// 覆盖首页、/progress、报告页、相对 data、错误页、非允许主机。
import { isReportUrl } from './url_rules.mjs';

const cases = [
  // [url, 期望是否认作报告页, 说明]
  ['https://mjai.ekyu.moe/', false, '首页'],
  ['https://mjai.ekyu.moe/index.html', false, '首页 index'],
  ['https://mjai.ekyu.moe/progress', false, '排队页'],
  ['https://mjai.ekyu.moe/progress?id=abc', false, '排队页带参数'],
  ['https://mjai.ekyu.moe/zh-cn.html', false, '语言首页'],
  ['https://mjai.ekyu.moe/error', false, '错误页'],
  ['https://mjai.ekyu.moe/killerducky/', false, 'ducky 空壳（无 data）'],
  ['https://mjai.ekyu.moe/killerducky/?data=', false, 'ducky 空 data'],
  ['https://mjai.ekyu.moe/killerducky/?data=/report/261118.json', true, '绝对路径 data'],
  ['https://mjai.ekyu.moe/killerducky/?data=report/261118.json', true, '相对路径 data'],
  ['https://mjai.ekyu.moe/killerducky/?data=https%3A%2F%2Fmjai.ekyu.moe%2Freport%2Fx.json', true, '编码的绝对 URL'],
  ['https://mjai.ekyu.moe/report/261118.json', true, '旧报告页'],
  ['https://mjai.ekyu.moe/report', true, '旧报告页根'],
  ['https://evil.example.com/killerducky/?data=/report/x.json', false, '非允许主机'],
  ['https://mjai.ekyu.moe.evil.com/killerducky/?data=/report/x.json', false, '伪造子域'],
  ['not a url', false, '不是 URL'],
  ['', false, '空串'],
];

let bad = 0;
for (const [u, want, why] of cases) {
  const got = !!isReportUrl(u);
  if (got !== want) {
    bad++;
    console.log(`FAIL ${why}: ${u} → ${got}（期望 ${want}）`);
  }
}
// data 参数要能被原样取出来（相对路径也要保住）
const rel = isReportUrl('https://mjai.ekyu.moe/killerducky/?data=report/261118.json');
if (!rel || rel.data !== 'report/261118.json') { bad++; console.log('FAIL 相对 data 取错:', rel); }
const abs = isReportUrl('https://mjai.ekyu.moe/killerducky/?data=/report/x.json&hlm=1m');
if (!abs || abs.data !== '/report/x.json') { bad++; console.log('FAIL 绝对 data 取错:', abs); }

console.log(bad ? `\n${bad} 条不通过` : `\n全部 ${cases.length + 2} 条通过`);
process.exit(bad ? 1 : 0);
