# 验证码换成 hCaptcha：改为统一人工验证（build 8）

## 现象

2026-11-24 / 25 两次提交都失败，日志里是：

```
PAGE_STATE {"form":true,"widget":true,"token":1,"tlen":"0","rtoken":0,"rtlen":"","api":"undefined","cf":false}
TOKEN_WAIT 0 15s {"form":true,"widget":true,"api":"undefined","cf":false,"rtoken":0,"rtlen":"","vis":"visible"}
VERIFICATION_TIMEOUT 300
```

浏览器明明开着、页面也停在首页表单上（`form=true`），但等满 5 分钟也拿不到 token。
即使人手动点了「我是人类」，程序照样卡住。

## 根因

**Mortal 官网把验证码从 Cloudflare Turnstile 换成了 hCaptcha。**

实测首页 DOM（Chrome 158）：

```
reviewForm 字段：… g-recaptcha-response, h-captcha-response, submitBtn
控件：<div class="h-captcha" data-sitekey="a71bde98-…">
脚本：https://js.hcaptcha.com/1/api.js
```

而旧代码全程只认 `cf-turnstile-response` / `.cf-turnstile`。字段名对不上，`readToken()`
永远返回空串 —— 所以 `cf:false`（没有 Cloudflare 脚本）不是网络故障，而是**官网根本
不再加载 Turnstile 了**。人点完复选框，token 写进的是 `h-captcha-response`，程序看不见。

这也解释了为什么「一开始能过」：11-23 及以前官网还是 Turnstile，之后切了。

## 为什么不自动识别验证码

- hCaptcha 除了图片挑战还有行为分析、指纹、无感判定，用脚本点复选框的成功率本身不稳定；
- 自动破解违反 hCaptcha 的服务条款，属于明确不能做的一类自动化；
- 就算这次侥幸点过，对方更新一次验证策略就全废，维护成本远高于「人手点一下」。

**结论：验证统一由人完成。** 程序负责把窗口摆到前台、把控件滚进视口、通过后自动
接着提交 —— 人只需要点一下。

## 本次改动

1. `tools/submit_auto.mjs`
   - 新增 `CAPTCHA_FIELDS = ['h-captcha-response', 'g-recaptcha-response', 'cf-turnstile-response']`
     与 `WIDGET_SEL`，`pageState / readToken / bringWidgetIntoView` 全部改为通用选择器；
     官网以后换回 Turnstile 或加 reCAPTCHA 都不用再改。
   - `SCRIPT_BUILD` 7 → 8。
   - `SHOW` 的默认值改为 true（`cfg.show !== false`）：除非显式关掉，否则一律把窗口摆出来。
   - `PAGE_STATE` / `TOKEN_WAIT` 增加 `hcap`、`rcap`、`tokName`（各字段当前长度），
     一眼能看出「脚本没加载」还是「脚本在、没人点」。
2. `app/main.py`
   - `SUBMIT_BUILD` 7 → 8；`show_browser` 默认 `True`。
   - 老配置迁移：`ui.captcha_manual_v1` 标记，首次启动把 `show_browser=false` 改回 `true`；
     之后用户主动取消勾选仍然有效。
   - 分析成功后不再把浏览器留到退出（以前 `show_browser` 为真就常驻一个 Chrome）。
   - 关掉翻译气泡：`repair_chrome_prefs()` 写入 `translate.enabled=false`，启动参数加
     `TranslateUI`。窗口现在默认在屏幕上，那个「是否翻译此网页」小框正好压住验证控件。
3. 界面与文档文案同步（设置页、常见问题、阶段提示）。

## 使用流程（现在的样子）

1. 粘贴牌谱，点「分析」→ 程序启动独立浏览器，窗口摆到前台，验证控件自动滚到可见处。
2. 在浏览器里勾选「我是人类」（需要时按提示选图）。
3. 通过后无需任何操作：程序读到 `h-captcha-response`，自动提交评分、下载报告、生成解读。
4. 5 分钟内没完成不算失败：应用给「继续等待 / 重新加载验证 / 取消」三个按钮，
   浏览器和页面都留着。

## 排错

| 现象 | 含义 | 处理 |
|---|---|---|
| `hcap:false` 且 `rcap:false`、`cf:false` | 验证脚本没加载 | 网络/代理拦了 `js.hcaptcha.com`、`newassets.hcaptcha.com`；换网络或关掉代理 |
| `widget:true`、`tokName:"h-captcha-response:0"` 一直不变 | 脚本在、没人点 | 在窗口里点复选框；看不到窗口点「显示验证窗口」 |
| 点完出现图片挑战 | hCaptcha 要求二次确认 | 按提示选图，选完自动继续 |
| `VERIFICATION_FAILED` | 挑战本身报错 | 点「重新加载验证」，或改用普通浏览器生成报告后粘回地址 |
| 弹「是否翻译此网页」 | 旧版本没关翻译 | build 8 已关闭（profile 级 + 启动参数）；仍出现就把该 Chrome 窗口关掉重开 |

## 验证记录（2026-11-25）

- 实测首页 DOM：`reviewForm` 含 `h-captcha-response`，两个 `.h-captcha` 控件，
  脚本为 `js.hcaptcha.com`，无 `challenges.cloudflare.com` → 根因确认。
- 旧代码在同一页面等 300 秒，`cf:false`、token 恒为 0 → 与用户日志一致。
- 点一下复选框后，hCaptcha 直接弹出**拼图挑战**（「移动正确的拼块以完成图案」），
  在解开之前 `h-captcha-response` 长度始终是 0 —— 这就是「必须人工」的实证：
  它不是点一下就过的无感验证，而是一道需要人操作的图灵测试。
- `WIDGET_IN_VIEW` 实测 `[295, 24, 302, 76, 667]`：定位到的是控件内部的 iframe
  （外层 div 被 hCaptcha 接管后高度会塌成 0，按容器量会误判「已经在视口里」）。
- `--selftest` 报 `submit_build 8`；日志首行 `SCRIPT_BUILD 8` 与程序一致；137 项测试通过。
