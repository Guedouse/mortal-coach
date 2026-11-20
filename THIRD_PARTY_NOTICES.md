# 第三方组件与许可声明

本文件列出**随本发行包分发的**第三方组件、它们的来源与许可。每个组件的许可原文放在
`licenses/` 目录；本文件只做索引与说明，不替代原文。

本项目自身的代码以 MIT 许可发布，见根目录 `LICENSE`。**不要把本文件的第三方声明理解成
“这些组件也是本项目 MIT 原创”**——它们的版权归各自作者。

---

## 1. 随包分发的组件

| 组件 | 版本 / 来源 | 许可 | 随包位置 | 许可文件 |
|---|---|---|---|---|
| Python | 3.13.14 x64 | PSF License 2.0 | `runtime/python/` | `licenses/python-PSF.txt`（运行时内另有 `runtime/python/LICENSE.txt`） |
| Pillow | 13.0.0 | HPND / PIL License | `runtime/python/Lib/site-packages/PIL/` | `licenses/pillow-LICENSE.txt` |
| Node.js | v22.22.2 x64 | MIT（含其捆绑的第三方组件） | `runtime/node/` | `licenses/node-MIT.txt` |
| i18next | 随包版本 | MIT | `assets/kd/i18next.min.js` | `licenses/i18next-MIT.txt` |
| **killer_mortal_gui 前端** | 上游 `9f85c6ba7c554ad5957ed01e1dc36c7f3064ce40`（2025-09-26） | MIT，Copyright (c) 2025 Andy Olsen | `assets/kd/index.js`、`index.html`、`style.css`、`translations.js`（**在本项目里修改过**，见第 3 节） | `licenses/killer_mortal_gui-MIT.txt` |
| pywebview | 构建时冻结进 EXE | BSD 3-Clause | `mortal-coach.exe` | `licenses/pywebview-BSD-3-Clause.txt` |
| pythonnet（`clr`） | pywebview 的 WebView2 后端依赖，冻结进 EXE | MIT | `mortal-coach.exe` | `licenses/pythonnet-MIT.txt` |
| PyInstaller bootloader | 冻结进 EXE（每个 PyInstaller 单文件程序都含它） | GPL 2.0 **附 Bootloader Exception**（允许把打包产物按任意许可分发） | `mortal-coach.exe` | `licenses/pyinstaller-bootloader-GPL2-with-exception.txt` |
| 立直麻将牌图 | FluffyStuff/riichi-mahjong-tiles | Public Domain / CC0 1.0 | `assets/kd/media/` | `licenses/riichi-mahjong-tiles-CC0.txt` |
| Noto Sans SC（中文字体） | Regular，SubsetOTF | SIL Open Font License 1.1 | `assets/fonts/NotoSansSC-Regular.otf` | `licenses/noto-sans-sc-OFL.txt` |
| Microsoft Edge WebView2 Runtime（系统 Evergreen 版） | **lite 版不随包分发**，用系统已安装的那份 | Microsoft 软件许可条款（用户与 Microsoft 之间成立） | — | 不分发则不产生再分发义务；见第 6.1 节 |
| Microsoft Edge WebView2 Runtime（Fixed Version） | 152.0.4191.53 x64 | Microsoft 软件许可条款（**专有软件**，允许随应用再分发，见 6.1） | `runtime/webview2/152.0.4191.53/`（**仅 full 版**） | `licenses/webview2-runtime-Microsoft.txt`（**来源声明 + 第 8 节用户通知，不是条款正文**；正文见 6.1 的官方链接） |

`mortal-coach.exe` 内冻结的依赖除 pywebview / pythonnet / PyInstaller bootloader 外，
还有它们自身携带的 .NET 程序集（`webview/lib/` 下的 WebView2 SDK 托管库）与 Python 标准库；
Python 与 Pillow 的许可随 `runtime/python/` 一并分发。

## 2. 牌图来源

`assets/kd/media/` 下的牌面与牌背图片来自 **FluffyStuff/riichi-mahjong-tiles**
（<https://github.com/FluffyStuff/riichi-mahjong-tiles>），该项目的 `LICENSE.md` 声明
为公有领域，并指向 CC0 1.0（<https://creativecommons.org/publicdomain/zero/1.0/>）。

## 2.1 中文字体

`scripts/mk_layout.py` 画「两种切法对照图」时要写中文。英文版 Windows 默认只有日文字体
（Yu Gothic / MS Gothic），汉字能画、中文专有字会变成方框，所以随包带一份
**Noto Sans SC Regular**（`assets/fonts/NotoSansSC-Regular.otf`，来源
<https://github.com/notofonts/noto-cjk>，SIL Open Font License 1.1，见
`licenses/noto-sans-sc-OFL.txt`）。查找顺序：随包字体 → 系统中文（雅黑/黑体/等线/宋体）
→ 系统日文；全都没有才退回 PIL 默认字体并在 stderr 打一行 warning。

## 3. 界面代码：基于 killer_mortal_gui（MIT）修改

`assets/kd/` 下的四个前端文件**是在上游 MIT 项目的基础上改的，不是本项目从零写的**：

- 上游：**killerducky/killer_mortal_gui**
  （<https://github.com/killerducky/killer_mortal_gui>），MIT，Copyright (c) 2025 Andy Olsen，
  比对基准 commit `9f85c6ba7c554ad5957ed01e1dc36c7f3064ce40`（2025-09-26），
  许可原文见 `licenses/killer_mortal_gui-MIT.txt`。
- 继承情况（按「去掉空行、忽略顺序后，上游行是否原样出现在我方文件里」统计，
  复核脚本：`tools/check_upstream_ratio.py`）：

| 文件 | 上游非空行 | 原样保留 | 本项目非空行 | 本项目新增/改写 |
|---|---|---|---|---|
| `index.js` | 2094 | 2078 | 3183 | ≈1105 |
| `style.css` | 474 | 464 | 1181 | ≈717 |
| `index.html` | 124 | 102 | 403 | ≈301 |
| `translations.js` | 1177 | 1170 | 1178 | ≈8 |

- 本项目在其上主要新增：**逐手中文解读面板**（`cp-rail` 分页、决定性要素置顶、牌面走真图）、
  **局/巡两个下拉 + 恶手标记**、**设置面板与牌谱库管理**、主页视图、`badlevel.js`（门槛与分档）、
  中文文案与 `translations.js` 的少量改写。牌理计算（`shanten.js` / `efficiency.js`）与
  画图、流水线、提交脚本是本项目自己的文件，见第 4 节。

**保留义务**：这四个文件继续按上游 MIT 分发，`licenses/killer_mortal_gui-MIT.txt` 里保留
原始版权声明；本项目新增部分的版权归 `LICENSE` 所载。修改此类文件时不要删除上游版权头。

## 3.1 与上游保持同步

`tools/check_upstream_ratio.py` 可以随时重算上面的继承比例（把上游对应文件放到 `%TEMP%`
下再跑）。升级上游时按这个顺序做：拉新 commit → 比对四个文件 → 合并 → 更新本节表格里的
commit 与行数 → 重新出包。

## 4. 牌理计算代码：本项目自有实现

`assets/kd/shanten.js`（向听数）与 `assets/kd/efficiency.js`（进张/受入）是本项目的
**独立实现**，没有复制第三方牌理库的源码：

- 两个文件描述的是麻将的通用算法（枚举面子 / 搭子 / 雀头，统计进张），算法规则本身
  属于通用方法；实现细节（数据结构、命名、剪枝方式、注释）由本项目维护。
- 它们的口径与 `scripts/mjcalc.py`（同样本项目自有）一致，前端与后端共用同一套规则，
  回归用例见 `tests/shanten_cases.json` 与 `tools/test_shanten.mjs`。
- 早期版本曾参考社区实现（其许可与本项目不同）。这些参考版本已整体替换为本项目实现，
  当前发行包中不含那些版本的代码。

**Git 历史的遗留问题（未解决，公开仓库前必须处理）**：本仓库的初始提交 `26a91aa` 里仍然
含有那版旧的 `shanten.js` / `efficiency.js`。如果直接把**完整历史**推到公开仓库，旧文件
仍会随历史分发，本节的说明就只对 HEAD 有效、对历史无效。处理方式二选一：

1. 先确认当初引入那一版时的实际授权，给历史版本补来源与许可说明；或
2. 保留现有私有开发仓库，另建一个**只含当前代码的干净提交**作为公开源码快照。

不要未经所有者同意重写已有历史。

**如果你要再分发本项目的牌理计算部分**：请以本文件与 `LICENSE` 为准（MIT）。如果将来
确实引入了 GPL 等强著佐权来源的代码，必须在本表登记并满足其源码义务，不能只保留 MIT。

## 5. 只在线调用、不随包分发的服务

| 服务 | 用途 | 说明 |
|---|---|---|
| Mortal（`https://mjai.ekyu.moe/`） | 对新牌谱评分 | 本包**不含** Mortal 推理引擎或模型权重，只按 HTTP 调用其公开服务；评分结果由该服务产生 |
| Cloudflare Turnstile | 提交牌谱时的人机验证 | 由提交浏览器访问，不由本应用实现 |

## 6. 构建期工具

**不随包**：Node 生态的构建脚本、`npm` 依赖等只在打包机器上用，不进发行包。

**随包（冻结进 EXE）**：PyInstaller 的 bootloader 与它注入的启动代码每个 onefile 程序都有，
所以它单列在第 1 节；其许可为 GPL 2.0 附 Bootloader Exception——该例外明确允许把打包
产物按任意许可分发，本项目因此仍可按 MIT 发布，但必须保留 `licenses/` 里那份许可原文。

## 6.1 界面内核 WebView2 与浏览器内核的分发方式

本项目的**默认发行包是 lite 版**（使用用户系统已有的浏览器与 WebView2）；full 版是**可选**的
便携变体，只附带 WebView2 界面运行时，不附提交浏览器。无论哪个版本，应用都不会往系统里安装或注册任何组件。

**lite 版**：发行包**不携带** WebView2 运行时，运行时由用户的 Windows 提供（Windows 11 内置，
Windows 10 随 Microsoft Edge 一起安装）。程序启动时只做两件事：

1. 读注册表 `HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-…}` 的 `pv`
   与 `location`，确认系统那份存在；
2. 认不到就弹出说明框，并给出微软官方下载页（`https://go.microsoft.com/fwlink/p/?LinkId=2124703`），
   由用户自行安装。应用不会静默下载或安装任何组件。

因为不分发该运行时，lite 版不承担其再分发义务；用户与 Microsoft 之间按其 Windows / Edge 条款成立。
`--selftest` 的 `webview2_source` 字段会显示 `system`。

**full 版**：仅随包分发 WebView2 界面运行时，不安装到系统：

- `runtime/webview2/152.0.4191.53/` —— 官方 **Fixed Version** 运行时，从微软官方 CDN 下载的
  `Microsoft.WebView2.FixedVersionRuntime.152.0.4191.53.x64.cab`（371,824,512 字节，
  SHA-256 `f8f200b57d6a7a71d380f777f5c0ea0f71f520048add21e15737121de9ba4f68`）用
  `expand` 原样解开，548 个文件，未删改任何文件。程序启动时把
  `WEBVIEW2_BROWSER_EXECUTABLE_FOLDER` 指向该目录，**不写注册表、不需要管理员权限**。
当前两种发行版本均不分发提交用 Chromium。Chrome／Edge 由用户自行安装，并适用其各自许可。仓库内可能保留历史 Chromium 许可文件，不能据此认定当前发行包附带该浏览器。

WebView2 运行时是**微软的专有软件**，不在本项目 MIT 许可范围内。这里要分清两件事：

- **条款正文**：微软公布的 *MICROSOFT SOFTWARE LICENSE TERMS — MICROSOFT EDGE WEBVIEW2
  RUNTIME (FIXED VERSION)* 在
  `https://learn.microsoft.com/en-us/legal/configmgr/microsoft-edge-webview2`。本项目不复制、
  不摘要、不改写它，正文以该页面为准。
- **本项目的来源声明**：`licenses/webview2-runtime-Microsoft.txt` 记录版本、来源 URL、原始 CAB
  的字节数与 SHA-256、解压方式，以及按条款第 8 节必须转达给最终用户的两条通知
  （包含微软提供的软件、可能向微软发送使用信息；包含默认启用的 SmartScreen）。
  该文件明确标注自己「不是许可正文」，不以文件名暗示已附全文。

再分发依据是上述条款第 2 节（DISTRIBUTABLE CODE）：允许复制分发 object code，条件是应用
有显著主功能、向最终用户转达条款与通知、代码直接取自微软、并由分发者为微软提供抗辩与
赔偿。本项目按「原样附带、不修改」执行，**这不是本项目的授权**；二次分发 full 版请自行复核。

**Windows 10 的目录权限前提**（仅 full + Win10）：微软 Fixed Version 分发文档要求
（Fixed 120 起）给运行时目录授予两个 AppContainer SID 的读/执行权限，否则 Renderer 起不来：
`icacls <目录> /grant *S-1-15-2-2:(OI)(CI)(RX)` 与 `*S-1-15-2-1:(OI)(CI)(RX)`。程序启动时
会检查并自动补授；补不上就改用系统 WebView2，两者都不可用时给出可复制的命令并退出。
普通 ZIP 解压不会带上这两个 ACE，所以这一步不能省。Windows 11 不受该限制。

固定版不随系统更新：要升级就换 `runtime/webview2/<新版本>/` 目录并重新打包。

## 7. 维护约定

1. 新增任何第三方代码、字体、图片、运行时，必须先在本表登记来源、版本、许可，并把许可原文
   放进 `licenses/`，再进入发行包。
2. `build_release.py` 会检查 `licenses/` 是否随包带上（`REQUIRED_LICENSES`，full 版另加
   `FULL_LICENSES`）；缺文件时打包直接失败。
3. 本表与 `README.md` 的“开源与致谢”一节必须保持一致。
