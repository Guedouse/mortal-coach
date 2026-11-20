# -*- coding: utf-8 -*-
"""mortal-coach · Mortal 牌桌复盘（桌面版）

双击启动：内置本地服务（assets/ 为静态根）→ 打开窗口 → 主页。
主页可粘贴牌谱链接现场分析，历史列表按日期打开已分析的局。

两个目录，分开是刻意的（开源版要能整包拷走，又不能让个人牌谱跟着程序走）：
  · APP_ROOT  —— 程序本体（exe / assets / scripts / tools / runtime），只读也能跑
  · LIB       —— 牌谱库（report / coach / img_layout / logs / bad_moves.json），可在设置里改
"""
import json
import atexit
import ctypes
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

ALLOWED_HOSTS = {"mjai.ekyu.moe"}
MODELS = ("4.1c", "4.1b", "4.1a", "4.0", "3.0")
SEAT_CN = ("东", "南", "西", "北")
APP_NAME = "mortal-coach"
APP_TITLE = "mortal-coach · Mortal 牌桌复盘"

# Windows 子进程默认会创建控制台窗口。桌面版把分析进程作为后台任务运行，
# 因此统一隐藏窗口，避免黑框闪现，也避免用户误以为应用异常退出。
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
HIDDEN_STARTUPINFO = None
if os.name == "nt":
    try:
        HIDDEN_STARTUPINFO = subprocess.STARTUPINFO()
        HIDDEN_STARTUPINFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        HIDDEN_STARTUPINFO.wShowWindow = subprocess.SW_HIDE
    except Exception:
        HIDDEN_STARTUPINFO = None


def hidden_process_kwargs():
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = CREATE_NO_WINDOW
    if HIDDEN_STARTUPINFO is not None:
        kw["startupinfo"] = HIDDEN_STARTUPINFO
    return kw


def gui_process_kwargs():
    """给**带界面的**子进程（Chrome）用：只关控制台，绝不能带 SW_HIDE。

    STARTF_USESHOWWINDOW + SW_HIDE 会作用到进程的顶层窗口，Chrome 照做 ——
    窗口建出来就是隐藏的，`--window-position` 放哪儿都看不见，
    设置里勾了「显示浏览器窗口」也没用，人机验证就永远没人能点。
    要「用户看不到」请用 `--window-position=-32000,-32000` 挪到屏幕外。
    """
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = CREATE_NO_WINDOW
    return kw


def child_env():
    """子进程环境：把程序目录与牌谱库目录传下去，脚本据此定位数据。"""
    e = dict(os.environ)
    e["MC_APP"] = str(APP_ROOT)
    e["MC_LIB"] = str(LIB)
    e["PYTHONIOENCODING"] = "utf-8"
    # 库锁是父子授权而不是层层抢：本进程持锁时告诉子进程「爹已经拿着了」，
    # 子进程（pipeline_one / mk_coach）就不再自己去 lock，否则会把自己爹锁死。
    # 没持锁时必须把这两个变量清掉，不能把上一轮的环境带下去。
    if LIB_EXCLUSIVE and _LIB_LOCK:
        e["MC_LIB_LOCK_OWNER"] = str(os.getpid())
        e["MC_LIB_LOCK_PATH"] = str(Path(LIB).resolve())
    else:
        e.pop("MC_LIB_LOCK_OWNER", None)
        e.pop("MC_LIB_LOCK_PATH", None)
    # 恶手入库门槛由设置决定；脚本自己也读配置文件，这里多传一份免得路径不一致
    try:
        e["MC_BAD_THRESH"] = str(norm_bad(CONFIG.get("bad"))["thresh"])
    except Exception:
        pass
    # 调试端口只传本进程启动的那个；外部残留的 CDP_PORT 一律清掉，
    # 否则可能把提交脚本指到别人的浏览器上。
    if CDP_PORT:
        e["CDP_PORT"] = str(CDP_PORT)
    else:
        e.pop("CDP_PORT", None)
    return e


def find_root():
    """程序根：exe 所在的发布目录，或源码里的上一级（含 assets/kd/index.html）。"""
    cands = []
    if getattr(sys, "frozen", False):
        cands.append(Path(sys.executable).resolve().parent)
    here = Path(__file__).resolve().parent
    cands += [here.parent, Path.cwd()]
    for c in cands:
        if (c / "assets" / "kd" / "index.html").exists():
            return c
    return cands[0]


APP_DIR = Path(__file__).resolve().parent
APP_ROOT = find_root()
ASSETS = APP_ROOT / "assets"
KD = ASSETS / "kd"

# 路径解析只有一份实现，在 scripts/paths.py；GUI 不再自己写一套，
# 否则配 `%VAR%/games` 这种值时 GUI 会展开、BAT 不展开，两边指向不同目录。
sys.path.insert(0, str(APP_ROOT / "scripts"))
try:
    import paths as PATHS
except Exception:                    # scripts/ 被删掉了也别整个崩掉
    PATHS = None

# ---------------- 配置 ----------------
# 便携优先：配置只认程序目录下的 mortal-coach.json（整个文件夹可以拷着走）。
# 程序目录不可写（比如装在 Program Files）才退到用户目录，且按程序目录分开存，
# 免得同一台机器上两份副本互相读到对方的库。
CONFIG_FILE = APP_ROOT / "mortal-coach.json"


def _instance_key():
    """按程序目录算一个稳定短标识。两份副本 A/B 各自一份配置与缓存。"""
    if PATHS:
        return PATHS.instance_key(APP_ROOT)
    import hashlib
    raw = str(APP_ROOT.resolve()).lower().encode("utf-8", "replace")
    return hashlib.sha1(raw).hexdigest()[:12]


def instance_dir():
    """本副本专属的用户目录（只读安装时放配置、库与 WebView 缓存）。"""
    if PATHS:
        return PATHS.instance_dir(APP_ROOT)
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_NAME / "instances" / _instance_key()


USER_CONFIG = instance_dir() / "config.json"
DEFAULT_CONFIG = {
    "library": "",          # 牌谱库目录；留空 = <程序目录>/library
    "chrome": "",           # 浏览器路径；留空 = 自动查找 Chrome / Edge
    "python": "",           # 解读流水线解释器；留空 = 包内 runtime 或系统 Python
    "node": "",             # 提交脚本运行时；留空 = 包内 runtime 或系统 Node
    "show_browser": False,  # 提交牌谱时是否把浏览器窗口显示出来（默认挪到屏幕外）
    # 恶手门槛与分级：门槛之上全部解析，严重 / 中等只区分权重差（巡目颜色）
    #   thresh = 权重差入库门槛 → 低于它的手不进库（改完要重跑流水线）
    #   gap    = 门槛之上再分「严重」，其余为「中等」
    #   loss   = 期望损失 Q → 解读面板右上角的「损失 严重/中等/轻微」
    # 与 assets/kd/badlevel.js 的 DEFAULTS 必须一致。
    "bad": {
        "thresh": 0.10,
        "gap": {"severe": 0.50},
        "loss": {"severe": 0.70, "medium": 0.30},
    },
    # 页面状态（首次引导是否已读等）。放配置里而不是 localStorage：
    # 换机器 / 清 webview 缓存都不会把「已经看过教程」弄丢。
    "ui": {},
}


def _can_write(d):
    try:
        t = Path(d) / ".mc_write_test"
        t.write_text("x", encoding="utf-8")
        t.unlink()
        return True
    except Exception:
        return False


def config_path():
    """**该往哪写**配置。

    便携模式：优先程序目录下的 `mortal-coach.json`。程序目录不可写（装在 Program Files、
    只读共享盘）才写按实例分开的用户目录 —— 注意是「不可写才换」，不是「存在就用」，
    否则一份只读的旧配置会让设置里的所有改动都静默丢失。

    **永远不读写 `%APPDATA%/mortal-coach/config.json`**：那是别的副本（或旧版本）留下的，
    读进来会让人以为「这台机器莫名多了一份别人的牌谱」。要搬旧库，去设置里主动选目录。
    """
    if PATHS:
        return PATHS.config_save_path(APP_ROOT, local=CONFIG_FILE, instance=USER_CONFIG)
    if _can_write(APP_ROOT):
        return CONFIG_FILE
    return USER_CONFIG


def config_read_paths():
    """读配置的顺序：**活动配置优先**，另一份只在活动配置还不存在时当种子。

    活动配置就是 `config_path()` 算出来的「该往哪写」那份。两者必须是同一套判定，
    否则只读安装目录里那份出厂默认值会一直盖住用户刚保存的新值：界面上显示保存成功，
    刷新或重启后又变回去（这一条是第三轮审计实测出来的）。
    """
    if PATHS:
        return PATHS.config_read_paths(APP_ROOT, local=CONFIG_FILE, instance=USER_CONFIG)
    active = config_path()
    seed = USER_CONFIG if active == CONFIG_FILE else CONFIG_FILE
    return [active] if seed == active else [active, seed]


def norm_bad(raw):
    """把配置里的 bad 归一成新结构，并兼容旧写法。

    现版是 `{thresh, gap:{severe}, loss:{severe,medium}}`：
      · thresh —— 入库门槛（权重差），低于它的手不进库；门槛之上全部分析；
      · gap.severe —— 门槛之上再分严重 / 中等（只影响巡目颜色）；
      · loss —— 徽章上的「损失 严重 / 中等 / 轻微」，与颜色无关。
    旧写法 `{metric,severe,medium}` 与 `{gap:{severe,medium}}`（上一版三档，medium 即门槛）
    都能读，迁移后不再有 levels 那一层。
    """
    raw = raw if isinstance(raw, dict) else {}
    out = {
        "thresh": DEFAULT_CONFIG["bad"]["thresh"],
        "gap": dict(DEFAULT_CONFIG["bad"]["gap"]),
        "loss": dict(DEFAULT_CONFIG["bad"]["loss"]),
    }

    def put(container, key, val, hi=1.0):
        try:
            container[key] = max(0.0, min(hi, float(val)))
        except (TypeError, ValueError):
            pass

    if raw.get("metric") in ("gap", "qloss") and not raw.get("gap") and not raw.get("loss"):
        if raw["metric"] == "qloss":
            for k in ("severe", "medium"):
                if k in raw:
                    put(out["loss"], k, raw[k], 5.0)
        else:
            if "medium" in raw:
                put(out, "thresh", raw["medium"])
            if "severe" in raw:
                put(out["gap"], "severe", raw["severe"])
    if "thresh" in raw:
        put(out, "thresh", raw["thresh"])
    src = raw.get("gap")
    if isinstance(src, dict):
        if "severe" in src:
            put(out["gap"], "severe", src["severe"])
        # 上一版三档配置里的 gap.medium 就是入库门槛
        if "thresh" not in raw and "medium" in src:
            put(out, "thresh", src["medium"])
    src = raw.get("loss")
    if isinstance(src, dict):
        for k in ("severe", "medium"):
            if k in src:
                put(out["loss"], k, src[k], 5.0)
    # 严重线必须落在门槛之上，否则「严重」这一档永远为空
    if out["gap"]["severe"] <= out["thresh"]:
        out["gap"]["severe"] = round(min(1.0, out["thresh"] + 0.01), 3)
    # Q 刻度：严重必须高于中等
    if out["loss"]["severe"] <= out["loss"]["medium"]:
        out["loss"]["medium"] = round(max(0.0, out["loss"]["severe"] - 0.01), 3)
    return out


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    cfg["bad"] = norm_bad(None)
    cfg["ui"] = {}
    for p in config_read_paths():
        try:
            if p.exists():
                d = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(d, dict):
                    for k, v in d.items():
                        if k not in DEFAULT_CONFIG:
                            continue
                        if k in ("bad", "ui") and isinstance(v, dict):
                            if k == "bad":
                                cfg["bad"] = norm_bad(v)
                            else:
                                cfg["ui"].update(v)
                        else:
                            cfg[k] = v
                    break
        except Exception:
            continue
    return cfg


def save_config(cfg):
    p = config_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return p
    except Exception:
        return None


def resolve_library(cfg):
    """牌谱库目录：留空 → 程序目录下的 library/（便携）；支持 ~ 与环境变量。

    解析规则与 BAT / rebuild_all 共用 `scripts/paths.py` 那一份，
    所以 `library` 填 `%USERPROFILE%/games` 时两边落到同一个目录。
    """
    raw = str((cfg or {}).get("library") or "").strip()
    if PATHS:
        return PATHS.library_value(raw, APP_ROOT)
    if not raw:
        return (APP_ROOT / "library").resolve()
    q = Path(os.path.expandvars(os.path.expanduser(raw)))
    if not q.is_absolute():
        q = APP_ROOT / q
    return q.resolve()


CONFIG = load_config()
LIB = resolve_library(CONFIG)
REPORT = LIB / "report"
COACH = LIB / "coach"
IMGS = LIB / "img_layout"
DATA = LIB
LOGS = LIB / "logs"
WORK = LIB / "work"
RUNTIME = APP_ROOT / "runtime"
TOOLS = APP_ROOT / "tools"
SCRIPTS = APP_ROOT / "scripts"


def refresh_paths():
    """设置里改了牌谱库目录后重新绑定派生路径。"""
    global CONFIG, LIB, REPORT, COACH, IMGS, DATA, LOGS, WORK
    CONFIG = load_config()
    LIB = resolve_library(CONFIG)
    REPORT, COACH, IMGS = LIB / "report", LIB / "coach", LIB / "img_layout"
    DATA, LOGS, WORK = LIB, LIB / "logs", LIB / "work"


def ensure_library():
    for d in (LIB, REPORT, COACH, IMGS, LOGS, WORK):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


# 牌谱库的独占锁。
#   LIB_EXCLUSIVE  False = 不能写（只允许看）
#   LIB_STATE      "ok" / "busy"（别人持锁）/ "denied"（锁文件建不出来）
LIB_EXCLUSIVE = True
LIB_STATE = "ok"
_LIB_LOCK = None


def _acquire(lib):
    """拿锁，返回 (status, handle)。没有 paths 模块时才走这段兜底。"""
    if PATHS:
        return PATHS.acquire_lock(lib)
    if os.name != "nt":
        return "ok", None
    try:
        import msvcrt
        f = open(Path(lib) / ".mc-lock", "a+b")
    except OSError:
        return "denied", None
    try:
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        f.close()
        return "busy", None
    return "ok", f


def lock_library(lib=None):
    """给牌谱库加跨进程独占锁。

    两个副本把库指到同一个网盘 / 移动盘目录时，同时分析或删除会互相覆盖
    `bad_moves.json`、互相删对方的 DevToolsActivePort。`threading.Lock` 只管本进程，
    所以这里用文件锁。进程结束（含崩溃）时系统自动释放，不会留下要手工清理的僵尸锁。

    三种结果都要区分：`busy` 是别人在写，`denied` 是连锁文件都建不出来（权限/只读介质）。
    后者不能当成「拿到了」—— 既然确认不了有没有别的写入者，就不该放行写。
    """
    global _LIB_LOCK, LIB_EXCLUSIVE, LIB_STATE
    status, h = _acquire(lib or LIB)
    if status == "ok":
        _LIB_LOCK = h            # 挂着不关，进程活着就一直占着
        LIB_EXCLUSIVE, LIB_STATE = True, "ok"
        if PATHS:
            PATHS.stamp_lock_owner(lib or LIB)
        return True
    _LIB_LOCK = None
    LIB_EXCLUSIVE, LIB_STATE = False, status
    return False


def unlock_library():
    """放掉当前库的锁（切库时先拿新的、再放旧的）。"""
    global _LIB_LOCK
    h, _LIB_LOCK = _LIB_LOCK, None
    try:
        if hasattr(h, "close"):
            h.close()
    except Exception:
        pass


def lib_busy_msg(short=False):
    """库不能写时的统一措辞：说清楚是「别人在写」还是「锁都建不出来」。"""
    if LIB_STATE == "denied":
        return (f"没法在 {LIB} 里建锁文件（权限不足或只读位置），"
                "确认不了有没有别的窗口在写，所以这次不写库。换个可写目录再试。")
    if short:
        return "这个牌谱库正被另一个 Mortal Coach 使用，先关掉那个窗口再操作（否则索引会写乱）"
    return (f"这个牌谱库正被另一个 Mortal Coach 写入：{LIB}。"
            "关掉那个窗口再分析，否则恶手记录会互相覆盖。")


def _exe(*parts):
    p = RUNTIME.joinpath(*parts)
    return str(p) if p.exists() else ""


def find_py():
    """跑解读流水线的解释器。

    顺序：设置里显式指定的 → 环境变量 → 包内 runtime/python → PATH → 源码模式的 sys.executable。
    显式设置放在包内之前，否则「高级：运行时路径」填了也不会生效（用户以为能换，实际被包内顶掉）。
    注意：冻结后 sys.executable 是 mortal-coach.exe，绝不能拿它当解释器。
    """
    cands = [
        (CONFIG.get("python") or "").strip(),
        os.environ.get("MORTAL_COACH_PY") or "",
        os.environ.get("MORTALCOACH_PY") or "",
        _exe("python", "python.exe"),
    ]
    from shutil import which
    for c in cands:
        if c and Path(c).exists():
            return c
    p = which("python")
    if p:
        return p
    if not getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        if exe.name.lower().startswith("python") and exe.exists():
            return str(exe)
    return ""


def find_node():
    """顺序同 find_py：设置 → 环境变量 → 包内 runtime/node → PATH。"""
    cands = [
        (CONFIG.get("node") or "").strip(),
        os.environ.get("MORTAL_COACH_NODE") or "",
        os.environ.get("MORTALCOACH_NODE") or "",
        _exe("node", "node.exe"),
    ]
    for c in cands:
        if c and Path(c).exists():
            return c
    from shutil import which
    return which("node") or which("node.exe") or ""


CHROME_CANDIDATES = [
    r"C:/Program Files/Google/Chrome/Application/chrome.exe",
    r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    r"%LOCALAPPDATA%/Google/Chrome/Application/chrome.exe",
    r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    r"C:/Program Files/Microsoft/Edge/Application/msedge.exe",
]


def bundled_chrome():
    """随包的 Chromium 目录（runtime/chromium），没有就返回空串。

    严格「解压即用」的 full 版需要它：把 Chromium 的完整目录（不只是 chrome.exe，
    *.dll、locales、resources.pak 都要）放进 `runtime/chromium/`，这里会优先用它。
    lite 版不带这个目录，于是退回系统安装的浏览器。
    """
    base = RUNTIME / "chromium"
    cands = [base / "chrome.exe", base / "chrome-win" / "chrome.exe",
             base / "msedge.exe"]
    try:
        cands += [d / "chrome.exe" for d in sorted(base.iterdir(), reverse=True)]
    except Exception:
        pass
    for c in cands:
        try:
            if c.exists():
                return str(c)
        except Exception:
            continue
    return ""


# 本次实际选中的浏览器来自哪一层，设置页与自检都显示出来。
#   settings = 用户指定的路径；env = MORTAL_COACH_CHROME；
#   system   = 常见安装位置/注册表里的正式版 Chrome/Edge；
#   bundled  = full 包内 runtime/chromium
CHROME_SOURCE = ""
CHROME_NOTE = ""


def chrome_candidates():
    """按优先级列出**存在**的浏览器候选 [(路径, 来源), ...]，已去重。

    顺序：用户指定 → 环境变量 → 系统正式版 Chrome/Edge → full 包内 Chromium → 注册表。

    随包那份排在系统后面：它是 Chromium 快照，版本号与发布通道都和用户日常
    浏览器不同，Cloudflare 对它的信任度没有保证；把它排前面会让「本来用系统
    Chrome 跑得好好的」用户在没有改任何设置的情况下换内核。full 版的价值是
    「没装浏览器也能用」，所以只在找不到系统浏览器时兜底。
    """
    seen, out = set(), []

    def add(p, src):
        if not p:
            return
        try:
            p = os.path.expandvars(str(p))
            key = os.path.normcase(os.path.abspath(p))
        except Exception:
            return
        if key in seen or not Path(p).exists():
            return
        seen.add(key)
        out.append((p, src))

    add((CONFIG.get("chrome") or "").strip(), "settings")
    add(os.environ.get("MORTAL_COACH_CHROME") or "", "env")
    for p in CHROME_CANDIDATES:
        add(p, "system")
    add(bundled_chrome(), "bundled")
    # 注册表里 Chrome 的 App Paths 最可靠（自定义安装目录也能找到）
    if os.name == "nt":
        try:
            import winreg
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for exe in ("chrome.exe", "msedge.exe"):
                    try:
                        with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as k:
                            v = winreg.QueryValue(k, None)
                        add(v, "registry")
                    except Exception:
                        continue
        except Exception:
            pass
    return out


def find_chrome():
    """本次该用哪个浏览器（第一个存在的候选），并把来源记进 CHROME_SOURCE。"""
    global CHROME_SOURCE
    cands = chrome_candidates()
    if not cands:
        CHROME_SOURCE = ""
        return ""
    CHROME_SOURCE = cands[0][1]
    return cands[0][0]


def webview2_root():
    """包内固定版 WebView2 Runtime 的目录（runtime/webview2），没有就返回空串。

    形如 `runtime/webview2/msedgewebview2.exe`，或 `runtime/webview2/<版本号>/msedgewebview2.exe`
    （官方 Fixed Version 包解压后多一层版本目录）。
    """
    base = RUNTIME / "webview2"
    if not base.exists():
        return ""
    if (base / "msedgewebview2.exe").exists():
        return str(base)
    try:
        for d in sorted(base.iterdir(), reverse=True):
            if d.is_dir() and (d / "msedgewebview2.exe").exists():
                return str(d)
    except Exception:
        pass
    return ""


WEBVIEW2_GUID = r"{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
# 官方 Evergreen 引导安装器（1.9 MB，装完不需要重启）
WEBVIEW2_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
WEBVIEW2_PAGE = "https://developer.microsoft.com/microsoft-edge/webview2/"


def webview2_system():
    r"""系统装没装 Evergreen WebView2 Runtime。返回 (版本号, 安装目录)，没装是 ("", "")。

    先读 EdgeUpdate 注册表（Win11 自带、Win10 装过 Edge 就有）：`pv` 是版本、
    `location` 是 `<...>\Microsoft\EdgeWebView\Application`（注意是 EdgeWebView，
    不是 EdgeWebView2），下面还有一层版本目录。注册表被清理过就按目录兜底。
    """
    if os.name != "nt":
        return "", ""
    try:
        import winreg
    except Exception:
        return "", ""
    tail = "Microsoft\\EdgeUpdate\\Clients\\{" + WEBVIEW2_GUID[1:]
    keys = ((winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\WOW6432Node\\" + tail),
            (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\" + tail),
            (winreg.HKEY_CURRENT_USER, "Software\\" + tail))
    for hive, sub in keys:
        try:
            with winreg.OpenKey(hive, sub) as k:
                ver = str(winreg.QueryValueEx(k, "pv")[0] or "")
                if not ver or ver == "0.0.0.0":
                    continue
                try:
                    loc = str(winreg.QueryValueEx(k, "location")[0] or "")
                except Exception:
                    loc = ""
                if loc:
                    exe = Path(loc) / ver / "msedgewebview2.exe"
                    if exe.exists():
                        return ver, str(exe.parent)
                return ver, loc
        except Exception:
            continue
    # 注册表被清理/精简过时的兜底：直接看安装目录
    bases = [os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
             r"C:\Program Files (x86)", r"C:\Program Files"]
    for b in bases:
        if not b:
            continue
        for name in ("EdgeWebView", "EdgeWebView2"):
            app = Path(b) / "Microsoft" / name / "Application"
            try:
                for d in sorted(app.iterdir(), reverse=True):
                    if (d / "msedgewebview2.exe").exists():
                        return d.name, str(d)
            except Exception:
                continue
    return "", ""


def bundled_webview2_version():
    """随包固定版 WebView2 的版本号 = 目录名（`runtime/webview2/<版本>/`）。

    官方固定版包解压出来就是「版本号」这一层，用它比读 exe 属性稳，也不用
    为此加载 ctypes 的版本 API。目录是拍平的（`runtime/webview2/msedgewebview2.exe`）
    时没有版本号可读，就报 "bundled"。
    """
    if not WEBVIEW2:
        return ""
    try:
        name = Path(WEBVIEW2).name
        return name if name[:1].isdigit() else "bundled"
    except Exception:
        return "bundled"


NODE = find_node()
PY = find_py()
CHROME = find_chrome()
WEBVIEW2 = webview2_root()                  # 随包的固定版（可选，没带就是空）
WEBVIEW2_VER, WEBVIEW2_SYS = webview2_system()   # 系统那份
# 能不能开界面：随包固定版 > 系统 Evergreen
WEBVIEW2_READY = bool(WEBVIEW2 or WEBVIEW2_VER or WEBVIEW2_SYS)


# ---------------- Windows 10 上 Fixed WebView2 的 AppContainer 权限 ----------------
# 官方（Fixed Version 分发文档）：Windows 10 上从 Fixed 120 起，未打包的 Win32 应用要给
# Fixed 目录授予下面两个 SID 的读/执行权限，否则 Renderer 起不来；Windows 11 不受影响。
#   icacls <目录> /grant *S-1-15-2-2:(OI)(CI)(RX)   ALL RESTRICTED APPLICATION PACKAGES
#   icacls <目录> /grant *S-1-15-2-1:(OI)(CI)(RX)   ALL APPLICATION PACKAGES
# 普通 ZIP 解压不会带上这两个 ACE，所以要自己检查、自己补。
WEBVIEW2_SID_PACKAGES = "S-1-15-2-1"
WEBVIEW2_SID_RESTRICTED = "S-1-15-2-2"
WEBVIEW2_ACL = "not-needed"                 # not-needed / ok / granted / failed / system-fallback
WEBVIEW2_ACL_NOTE = ""


def windows_build():
    """Windows 内部版本号：Win10 是 19041~19045，Win11 从 22000 起。非 Windows 返回 0。"""
    if os.name != "nt":
        return 0
    try:
        return int(sys.getwindowsversion().build)
    except Exception:
        return 0


def _dacl_sddl(path):
    """读目录 DACL 的 SDDL 文本，失败返回空串。

    为什么不用 `icacls` 的输出：中文 Windows 会把组名翻成「所有应用程序包」，
    按名字匹配必然失效；SDDL 里的 SID 是 `S-1-15-2-1` 这种与语言无关的字符串。
    """
    import ctypes
    from ctypes import wintypes

    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    adv.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID)]
    adv.GetNamedSecurityInfoW.restype = wintypes.DWORD
    adv.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(wintypes.DWORD)]
    adv.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
    k32.LocalFree.argtypes = [wintypes.LPVOID]

    sd = wintypes.LPVOID()
    # SE_FILE_OBJECT=1, DACL_SECURITY_INFORMATION=0x4
    if adv.GetNamedSecurityInfoW(str(path), 1, 0x00000004,
                                 None, None, None, None, ctypes.byref(sd)) != 0:
        return ""
    try:
        out = wintypes.LPWSTR()
        n = wintypes.DWORD()
        if not adv.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                sd, 1, 0x00000004, ctypes.byref(out), ctypes.byref(n)):
            return ""
        try:
            return out.value or ""
        finally:
            k32.LocalFree(out)
    finally:
        k32.LocalFree(sd)


def _acl_missing_sids(path):
    """目录 DACL 里缺的 AppContainer SID；读不到 ACL 返回 None（≠ 不缺）。

    注意 SDDL 会把 S-1-15-2-1（ALL APPLICATION PACKAGES）简写成别名 `AC`，
    S-1-15-2-2（ALL RESTRICTED APPLICATION PACKAGES）则保留完整 SID —— 两者都得认。
    只认「允许」型 ACE（以 A; 开头），deny 不算数。
    """
    sddl = _dacl_sddl(path)
    if not sddl:
        return None
    names = {WEBVIEW2_SID_PACKAGES: ("AC", WEBVIEW2_SID_PACKAGES),
             WEBVIEW2_SID_RESTRICTED: (WEBVIEW2_SID_RESTRICTED,)}
    missing = []
    for sid, alias in names.items():
        alt = "|".join(re.escape(a) for a in alias)
        if not re.search(r"\(A;(?:[^;]*;){4}(?:" + alt + r")\)", sddl):
            missing.append(sid)
    return missing


def webview2_acl_state(path=None):
    """随包 Fixed WebView2 的 AppContainer 权限状态 → (state, 说明)。

    state: `not-needed`（Win11/没随包/非 Windows）、`ok`、`missing`、`unknown`（读不到 ACL）。
    说明用 ASCII：--selftest 要在 cmd / 重定向里都看得懂，中文留给界面提示。
    """
    p = path or WEBVIEW2
    if not p:
        return "not-needed", "no bundled runtime"
    if os.name != "nt":
        return "not-needed", "not windows"
    build = windows_build()
    if build >= 22000:
        return "not-needed", f"windows 11 (build {build}): not affected"
    missing = _acl_missing_sids(p)
    if missing is None:
        return "unknown", "cannot read directory ACL"
    if missing:
        return "missing", "missing " + ", ".join(missing)
    return "ok", "both AppContainer SIDs present"


def _webview2_acl_cmd(path):
    lines = [f'icacls "{path}" /grant *{WEBVIEW2_SID_RESTRICTED}:(OI)(CI)(RX)',
             f'icacls "{path}" /grant *{WEBVIEW2_SID_PACKAGES}:(OI)(CI)(RX)']
    return "\n".join(lines)


def grant_webview2_acl(path=None):
    """用官方给的两条 icacls 给目录补权限。返回 (ok, 说明)。

    普通用户对自己解压出来的目录有 FullControl，能改 ACL；解压到 Program Files
    这类位置就需要管理员，失败时由调用方给出可复制的命令。
    """
    p = path or WEBVIEW2
    if not p:
        return False, "no bundled runtime"
    rcs = []
    for sid in (WEBVIEW2_SID_RESTRICTED, WEBVIEW2_SID_PACKAGES):
        try:
            r = subprocess.run(
                ["icacls", p, "/grant", f"*{sid}:(OI)(CI)(RX)", "/C", "/Q"],
                capture_output=True, text=True, encoding="mbcs", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as e:
            return False, f"icacls not runnable: {type(e).__name__}"
        if r.returncode != 0:
            rcs.append(f"rc={r.returncode}")
    if rcs:
        return False, "icacls failed (" + ", ".join(rcs) + ")"
    return True, "granted"


def prepare_webview2(interactive=True):
    """Win10 + 随包 Fixed：开窗前补权限；补不上就用系统 Evergreen 兜底。

    返回 True 继续启动，False 表示这台机器两者都不可用（调用方给中文说明）。
    """
    global WEBVIEW2, WEBVIEW2_ACL, WEBVIEW2_ACL_NOTE
    if not WEBVIEW2:
        WEBVIEW2_ACL, WEBVIEW2_ACL_NOTE = "not-needed", "using system runtime"
        return True
    state, note = webview2_acl_state()
    if state in ("not-needed", "ok"):
        WEBVIEW2_ACL, WEBVIEW2_ACL_NOTE = ("ok" if state == "ok" else state), note
        return True
    ok, msg = grant_webview2_acl()
    if ok and webview2_acl_state()[0] == "ok":
        WEBVIEW2_ACL = "granted"
        WEBVIEW2_ACL_NOTE = "granted AppContainer RX on bundled runtime"
        return True
    # 补不上：Win10 上退回系统 Evergreen（有的话），并如实说明用的是哪一份
    if WEBVIEW2_VER or WEBVIEW2_SYS:
        WEBVIEW2_ACL = "system-fallback"
        WEBVIEW2_ACL_NOTE = f"bundled runtime not usable ({msg}); using system runtime"
        WEBVIEW2 = ""
        return True
    WEBVIEW2_ACL = "failed"
    WEBVIEW2_ACL_NOTE = f"bundled runtime not usable ({msg}); no system runtime either"
    if interactive:
        _msgbox("Mortal Coach 的界面内核需要目录权限，这台机器上没能自动补上。\n\n"
                "原因：" + WEBVIEW2_ACL_NOTE + "\n\n"
                "两个办法任选一个：\n"
                "1) 用管理员身份运行一次下面的命令（引号内的路径按实际位置）：\n\n"
                + _webview2_acl_cmd(WEBVIEW2 or r"…\runtime\webview2\<版本>") + "\n\n"
                "2) 装一次系统 WebView2 运行时（约 2 MB），程序会自动改用它。",
                APP_TITLE, 0x10)
    return False



def machine_id():
    """这台机器的标识，用来判断 chrome-profile 是不是从别的机器整包拷过来的。"""
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\Microsoft\Cryptography") as k:
                v, _ = winreg.QueryValueEx(k, "MachineGuid")
                if v:
                    return str(v).strip()
        except Exception:
            pass
    return (os.environ.get("COMPUTERNAME") or "unknown").strip()


def prepare_profile(prof):
    """浏览器 profile 是跟着文件夹走的，换机器会出事。

    Chrome 的 cookie 用 Windows DPAPI 加密，换机器解不开；旧 profile 里
    还可能留着「上次异常退出」的状态。表现就是首页打得开、人机验证却
    永远过不去（NO_TOKEN）。所以认出来是别人的 profile 就直接换一个新的
    —— 这个目录里没有值得挽留的东西（不存牌谱、不存登录）。
    """
    prof.mkdir(parents=True, exist_ok=True)
    stamp = prof / ".mc-machine"
    want = machine_id()
    try:
        old = stamp.read_text(encoding="utf-8").strip() if stamp.exists() else ""
    except Exception:
        old = ""
    if old != want and (prof / "Default").exists():
        dead = prof.with_name("chrome-profile.old")
        try:
            if dead.exists():
                shutil.rmtree(dead, ignore_errors=True)
            prof.rename(dead)
        except Exception:
            shutil.rmtree(prof, ignore_errors=True)
        prof.mkdir(parents=True, exist_ok=True)
    try:
        stamp.write_text(want, encoding="utf-8")
    except Exception:
        pass
    return prof


def env_problems():
    """启动自检：缺什么就直接说清楚，别等用户点了「分析」才神秘失败。"""
    bad = []
    if not PY:
        bad.append("缺少 Python 运行时（runtime/python/python.exe，或设置里指定）")
    if not NODE:
        bad.append("缺少 Node 运行时（runtime/node/node.exe，或设置里指定）")
    if not CHROME:
        bad.append("没找到 Chrome / Edge，提交牌谱需要它过人机验证（可在设置里指定路径）")
    if not WEBVIEW2_READY:
        bad.append("缺少 WebView2 运行时，界面打不开（Win11 自带；Win10 装过 Edge 一般也有，"
                   "没有就到 " + WEBVIEW2_PAGE + " 装一次）")
    elif WEBVIEW2:
        # 有 exe 不等于能用：Win10 上 Fixed >= 120 还要求目录带两个 AppContainer SID 的读执行权限
        acl_state, acl_note = webview2_acl_state()
        if acl_state in ("missing", "unknown"):
            bad.append(f"随包 WebView2 缺少 Windows 10 所需的目录权限（{acl_note}）："
                       "启动时会尝试自动补上；补不上需按提示用管理员执行 icacls，"
                       "或安装系统 WebView2 运行时")
    if not (ASSETS / "kd" / "index.html").exists():
        bad.append("缺少 assets 目录（页面与数据都在里面），请把整个文件夹一起拷贝")
    # 牌谱库不可写：继续跑会在分析最后一步才失败，那时用户已经等了几分钟
    if not _can_write(LIB if LIB.exists() else LIB.parent):
        bad.append(f"牌谱库目录不可写：{LIB}。把整个文件夹挪到有写权限的位置，"
                   "或在设置里把牌谱库改到别处")
    return bad


def port_open(port, host="127.0.0.1"):
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex((host, port)) == 0


def read_devtools_port(profile_dir):
    """Chrome 以 --remote-debugging-port=0 启动后，实际端口写在 profile 的
    DevToolsActivePort 第一行。用 0 让浏览器自己挑端口，就不会和用户开着的
    调试浏览器（常见 9222）抢，也不会误连到别人的实例。"""
    try:
        txt = (Path(profile_dir) / "DevToolsActivePort").read_text(encoding="utf-8", errors="ignore")
        return int((txt.splitlines() or [""])[0].strip())
    except Exception:
        return 0


def cdp_json(port, path, timeout=3.0):
    """读本地调试端口的 JSON 接口（/json/list、/json/version）。失败返回 None。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def cdp_page_targets(port):
    """当前可用的页面 target。空列表 = 还没有页面（about:blank 也算一个页面）。"""
    rows = cdp_json(port, "/json/list") or []
    return [t for t in rows if t.get("type") == "page"]


def cdp_browser_version(port):
    info = cdp_json(port, "/json/version") or {}
    return (info.get("Browser") or "").strip()


def find_window_by_pid(pid):
    """找某个进程自己的顶层浏览器窗口（Chrome_WidgetWin_1）。

    只看我们自己启动的那个 PID：不枚举全系统窗口去「猜」哪个是浏览器，
    避免误把用户日常 Chrome 抢到前台。
    """
    if os.name != "nt":
        return 0
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        p = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid:
            cls = ctypes.create_unicode_buffer(64)
            u32.GetClassNameW(hwnd, cls, 64)
            rect = wintypes.RECT()
            u32.GetWindowRect(hwnd, ctypes.byref(rect))
            if cls.value == "Chrome_WidgetWin_1" and rect.right - rect.left > 300:
                found.append(hwnd)
        return True

    u32.EnumWindows(_cb, 0)
    return found[0] if found else 0


# 本次进程实际使用的调试端口；只有 ensure_chrome 启动了浏览器才会非 0。
# submit_auto.mjs 通过 CDP_PORT 收到它，不去碰别的端口。
CDP_PORT = 0
# 浏览器就绪分两级：端口通（进程活着、能连调试协议）≠ 页面就绪（有 page target）。
# 只报「端口通」会把「打开了但一片空白」说成成功，排查时完全看不出区别。
CHROME_STATE = ""
CHROME_VER = ""

# ---------------------------------------------------------------- 构建标识
# 用户双击的是**冻结后的 EXE**，改 app/main.py 不会自动生效。以前出过
# 「源码修好了、EXE 还是旧的」这种混合状态，所以把身份显式报出来：
#   - EXE 构建时间取可执行文件自身的修改时间（改名/重打包必然变化）
#   - 外置 JS 自带 SCRIPT_BUILD，两边不一致时日志与设置里直接标红
SUBMIT_BUILD = 5          # 必须与 tools/submit_auto.mjs 的 BUILD 一致
# 勾了「显示浏览器」时等用户点验证的上限（秒）。MC_MANUAL_WAIT 只给排查/自测用。
MANUAL_WAIT_SEC = int(os.environ.get("MC_MANUAL_WAIT") or 300)
APP_BUILD = "2026-11-21"  # 源码构建号，发版时更新


def _exe_timestamp():
    """PE 头里的链接时间。**不能用文件 mtime**：用户从 ZIP 解压后 mtime 会变成
    解压时间，每个人看到的「版本」都不一样；PE 里的时间戳是编译时写死的。"""
    try:
        import struct
        with open(sys.executable, "rb") as f:
            d = f.read(4096)
        if len(d) < 0x40 or d[:2] != b"MZ":
            return 0
        off = struct.unpack_from("<I", d, 0x3C)[0]
        if off + 12 > len(d) or d[off:off + 4] != b"PE\0\0":
            return 0
        return struct.unpack_from("<I", d, off + 8)[0]
    except Exception:
        return 0


def build_id():
    """当前到底跑的是哪个构建：冻结包看 PE 编译时间，源码运行看源码构建号。"""
    if getattr(sys, "frozen", False):
        ts = _exe_timestamp()
        if ts:
            return "exe " + time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
        try:
            st = os.stat(sys.executable)
            return "exe " + time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
        except OSError:
            return "exe"
    return "source " + APP_BUILD


# ------------------------------------------------------------ 提交阶段状态
# 前端在 submit_link 的 Promise 还没返回时轮询 get_submit_status()，
# 这样「需要你点一下验证」能当场显示，而不是等三分钟拿到失败结果才知道。
SUBMIT_STATE = {
    "active": False, "stage": "", "detail": "", "wait": 0,
    "tag": "", "resumable": False, "started": 0.0, "updated": 0.0,
}
SUBMIT_LOCK = threading.Lock()


def submit_state_reset(tag=""):
    with SUBMIT_LOCK:
        SUBMIT_STATE.update({"active": True, "stage": "STARTING", "detail": "",
                             "wait": 0, "tag": tag, "resumable": False,
                             "started": time.time(), "updated": time.time()})


def submit_state_set(stage=None, detail=None, wait=None, resumable=None, active=None):
    with SUBMIT_LOCK:
        if stage is not None:
            SUBMIT_STATE["stage"] = stage
        if detail is not None:
            SUBMIT_STATE["detail"] = str(detail)[:300]
        if wait is not None:
            SUBMIT_STATE["wait"] = int(wait)
        if resumable is not None:
            SUBMIT_STATE["resumable"] = bool(resumable)
        if active is not None:
            SUBMIT_STATE["active"] = bool(active)
        SUBMIT_STATE["updated"] = time.time()


def submit_state_get():
    with SUBMIT_LOCK:
        d = dict(SUBMIT_STATE)
    d["elapsed"] = round(time.time() - d["started"], 1) if d.get("started") else 0
    return d


# submit_auto.mjs 的行 → 阶段。第一列是它输出的关键字。
def submit_stage_of(line):
    """把脚本的一行输出翻译成（阶段, 是否要立刻告诉用户）。"""
    t = line.strip()
    for key, stage in (("NEED_MANUAL", "AWAITING_VERIFICATION"),
                       ("VERIFICATION_REQUIRED", "AWAITING_VERIFICATION"),
                       ("VERIFICATION_TIMEOUT", "AWAITING_VERIFICATION"),
                       ("VERIFICATION_FAILED", "VERIFICATION_FAILED"),
                       ("TOKEN_OK", "SUBMITTING"),
                       ("SUBMIT_URL", "SUBMITTING"),
                       ("SUBMIT ", "SUBMITTING"),
                       ("REPORT ", "DOWNLOADING"),
                       ("PAGE_ERROR", "SUBMIT_REJECTED")):
        if t.startswith(key):
            return stage
    if t.startswith("wait ") and "/progress" in t:
        return "SCORING"
    return None



def no_token_hint(out, logp=None):
    """把 submit_auto 的 PAGE_STATE / NO_TOKEN_STATE 翻成用户能照做的说明。

    换机器后拿不到 Turnstile token 基本就三种：
      ① 首页压根没打开（断网 / 代理拦了）→ form=false
      ② 首页开了但 challenges.cloudflare.com 的脚本没加载 → cf=false
      ③ 脚本加载了，Cloudflare 这次要人工点「确认您是真人」→ 其余情况
    """
    st = {}
    for raw in re.findall(r"^(?:PAGE_STATE|NO_TOKEN_STATE)\s+(\{.*\})\s*$", out, re.M):
        try:
            d = json.loads(raw)
        except Exception:
            continue
        if isinstance(d, dict):
            st.update(d)
    if st.get("form") is False:
        msg = ("Chrome 里 Mortal 首页没打开（找不到提交表单）。这台机器到 mjai.ekyu.moe 的"
               "网络不通，或被代理 / 防火墙拦了 —— 先用浏览器打开 https://mjai.ekyu.moe/ 确认能加载。")
    elif st.get("cf") is False:
        msg = ("首页开了，但人机验证的脚本（challenges.cloudflare.com）没加载出来，"
               "属于网络问题：连不上 Cloudflare，换个网络或开代理再试。")
    elif st.get("widget") is False:
        msg = ("首页里没找到人机验证组件，可能页面只加载了一半。"
               "把那个 Chrome 窗口关掉，再点一次「分析」。")
    else:
        msg = ("人机验证这次要人工确认，自动点的没通过。程序会把 Chrome 窗口搬到屏幕正面："
               "在设置里勾上「显示浏览器窗口」再点一次「分析」，看到「确认您是真人」就点一下。")
    if logp is not None:
        msg += f"（详细过程见 logs/{Path(logp).name}）"
    return msg


class Handler(SimpleHTTPRequestHandler):
    """静态站 + 牌谱库路由。

    页面在 assets/ 下，但 report / coach / img_layout 三块个人数据在牌谱库里
    （用户可以改到任意目录），所以这里把两类 URL 都映射过去：
    页面里的相对路径 `coach/x.json`（= /kd/coach/…）和 coach json 里写死的 `/img_layout/…`。
    """

    def translate_path(self, path):
        clean = urlparse(path).path
        for pre, base in (("report", REPORT), ("coach", COACH), ("img_layout", IMGS)):
            for head in (f"/{pre}/", f"/kd/{pre}/"):
                if clean.startswith(head):
                    name = os.path.basename(clean[len(head):])
                    if name:
                        return str(base / name)
        return super().translate_path(path)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *a):
        pass


def serve(port):
    ThreadingHTTPServer.allow_reuse_address = True
    httpd = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(ASSETS)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def latest_game():
    idx = COACH / "index.json"
    if not idx.exists():
        return ""
    try:
        data = json.load(open(idx, encoding="utf-8"))
        return data[-1]["tag"] if data else ""
    except Exception:
        return ""


def tag_from_url(url):
    m = re.search(r"paipu=([0-9]{6})", url or "")
    if m:
        return m.group(1)
    m = re.search(r"([0-9]{6})", url or "")
    return m.group(1) if m else time.strftime("%y%m%d")


def guess_format(raw, fmt="auto"):
    """牌谱格式：auto 时按内容猜。返回 mjai 表单里的 input-method 值。"""
    raw = (raw or "").strip()
    if fmt and fmt != "auto":
        return fmt
    if raw.startswith("http://") or raw.startswith("https://"):
        return "log-url"
    if re.match(r"^\d+_[0-9a-f]{20,}$", raw, re.I):
        return "hime-mahjong-log-id"
    if raw.startswith("{"):
        return "tenhou6"
    if re.match(r"^[a-z0-9]{16,28}(@\d)?$", raw, re.I):
        return "riichi-city-log-id"
    return "log-url"


def normalize_pasted_input(raw):
    """按 Mortal 官网的粘贴行为取出第一个 http(s) 地址，并去掉复制尾部标点。"""
    s = str(raw or "").strip()
    m = re.search(r"https?://\S+", s, re.I)
    if m:
        s = s[m.start():].strip()
    else:
        # 从地址栏、聊天窗口复制时常丢掉协议头（game.maj-soul.com/1/?paipu=…）。
        # 只补「域名 + 路径」这种明显是网址的形态，别把一番街的对局 ID 也补成网址。
        if re.match(r"^(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?::\d+)?/\S*$", s):
            s = "https://" + s
    return s.rstrip("\t\r\n \u3002，,；;）)】]>")


def report_data_candidates_from_input(raw):
    """识别 Mortal 报告页或直接 report JSON 链接，返回受限的报告数据地址。"""
    u = urlparse(normalize_pasted_input(raw))
    if u.scheme not in ("http", "https") or (u.hostname or "") not in ALLOWED_HOSTS:
        return []
    path = u.path or ""
    if path.endswith(".json") and "/report/" in path:
        return [f"https://{u.hostname}{path}"]
    if "killerducky" in path and parse_qs(u.query).get("data"):
        return data_url_candidates(u.geturl())
    return []


def seat_from_log_id(raw):
    """一番街 / 姬麻将的对局 ID 末尾 @N 就是座位。"""
    m = re.search(r"@(\d)\s*$", raw or "")
    return m.group(1) if m else ""


def next_tag(base):
    """同日多局：261118 → 261118B → 261118C。写盘前再查一次，避免并发覆盖。"""
    if not (REPORT / f"{base}.json").exists() and not (COACH / f"{base}.json").exists():
        return base
    for c in "BCDEFGHIJKLMNOPQRSTUVWXYZ":
        if not (REPORT / f"{base}{c}.json").exists() and not (COACH / f"{base}{c}.json").exists():
            return base + c
    return base + "_" + time.strftime("%H%M%S")


def _ws_send_once(ws_url, obj, timeout=3.0):
    """最小 WebSocket 客户端，只发一帧（用来给浏览器下 Browser.close）。"""
    import base64 as _b64
    _, _, rest = ws_url.partition("://")
    hostport, _, path = rest.partition("/")
    host, _, port = hostport.partition(":")
    sock = socket.create_connection((host, int(port or 80)), timeout)
    try:
        key = _b64.b64encode(os.urandom(16)).decode()
        sock.sendall((f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\n"
                      "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            d = sock.recv(4096)
            if not d:
                return False
            buf += d
        if b"101" not in buf.split(b"\r\n")[0]:
            return False
        data = json.dumps(obj).encode()
        hdr = bytearray([0x81])
        if len(data) < 126:
            hdr.append(0x80 | len(data))
        elif len(data) < 65536:
            hdr.append(0x80 | 126)
            hdr += struct.pack(">H", len(data))
        else:
            hdr.append(0x80 | 127)
            hdr += struct.pack(">Q", len(data))
        mask = os.urandom(4)
        hdr += mask
        sock.sendall(bytes(hdr) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
        return True
    finally:
        try:
            sock.close()
        except Exception:
            pass


def cdp_browser_close(port):
    """请浏览器自己退出。比 terminate() 强：它会正常落盘 profile，
    下次启动不会弹「Chrome 未正常关闭 / 是否恢复页面」。

    **port 必填**：只关本应用启动的那个实例。给个默认 9222 会变成
    「顺手把用户自己的调试浏览器也关掉」。"""
    if not port:
        return False
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3) as r:
            v = json.loads(r.read().decode("utf-8"))
        ws = v.get("webSocketDebuggerUrl")
        return bool(ws) and _ws_send_once(ws, {"id": 1, "method": "Browser.close"})
    except Exception:
        return False


def repair_chrome_prefs(prof):
    """启动前把上次的「异常退出」标记抹掉，避免恢复页面气泡。"""
    for rel in ("Default/Preferences", "Preferences", "Local State"):
        f = Path(prof) / rel
        if not f.exists():
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        if rel.endswith("Local State"):
            pr = d.get("profile")
            if isinstance(pr, dict):
                pr.pop("exit_type", None)
            continue
        pr = d.setdefault("profile", {})
        if pr.get("exit_type") != "Normal" or pr.get("exited_cleanly") is not True:
            pr["exit_type"] = "Normal"
            pr["exited_cleanly"] = True
            try:
                f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass


# ---------------- Windows 原生选择框（纯 ctypes） ----------------
def _pick_folder_win(title, initial=""):
    """SHBrowseForFolderW：选目录。返回空串表示用户取消。"""
    from ctypes import wintypes

    class BROWSEINFOW(ctypes.Structure):
        _fields_ = [("hwndOwner", wintypes.HWND),
                    ("pidlRoot", ctypes.c_void_p),
                    ("pszDisplayName", wintypes.LPWSTR),
                    ("lpszTitle", wintypes.LPCWSTR),
                    ("ulFlags", wintypes.UINT),
                    ("lpfn", ctypes.c_void_p),
                    ("lParam", wintypes.LPARAM),
                    ("iImage", ctypes.c_int)]

    name = ctypes.create_unicode_buffer(260)
    bi = BROWSEINFOW()
    bi.hwndOwner = None
    bi.pszDisplayName = ctypes.cast(name, wintypes.LPWSTR)
    bi.lpszTitle = title
    # RETURNONLYFSDIRS | NEWDIALOGSTYLE | EDITBOX
    bi.ulFlags = 0x00000001 | 0x00000040 | 0x00000010
    shell32 = ctypes.windll.shell32
    shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
    pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
    if not pidl:
        return ""
    out = ctypes.create_unicode_buffer(1024)
    shell32.SHGetPathFromIDListW(ctypes.c_void_p(pidl), out)
    try:
        ctypes.windll.ole32.CoTaskMemFree(ctypes.c_void_p(pidl))
    except Exception:
        pass
    return out.value


def _pick_file_win(title, initial="", filt=""):
    """GetOpenFileNameW：选文件。filt 用 \\0 分隔，以双 \\0 结尾。"""
    from ctypes import wintypes

    class OPENFILENAMEW(ctypes.Structure):
        _fields_ = [("lStructSize", wintypes.DWORD),
                    ("hwndOwner", wintypes.HWND),
                    ("hInstance", wintypes.HINSTANCE),
                    ("lpstrFilter", wintypes.LPCWSTR),
                    ("lpstrCustomFilter", wintypes.LPWSTR),
                    ("nMaxCustFilter", wintypes.DWORD),
                    ("nFilterIndex", wintypes.DWORD),
                    ("lpstrFile", wintypes.LPWSTR),
                    ("nMaxFile", wintypes.DWORD),
                    ("lpstrFileTitle", wintypes.LPWSTR),
                    ("nMaxFileTitle", wintypes.DWORD),
                    ("lpstrInitialDir", wintypes.LPCWSTR),
                    ("lpstrTitle", wintypes.LPCWSTR),
                    ("Flags", wintypes.DWORD),
                    ("nFileOffset", wintypes.WORD),
                    ("nFileExtension", wintypes.WORD),
                    ("lpstrDefExt", wintypes.LPCWSTR),
                    ("lCustData", wintypes.LPARAM),
                    ("lpfnHook", ctypes.c_void_p),
                    ("lpTemplateName", wintypes.LPCWSTR),
                    ("pvReserved", ctypes.c_void_p),
                    ("dwReserved", wintypes.DWORD),
                    ("FlagsEx", wintypes.DWORD)]

    buf = ctypes.create_unicode_buffer(1024)
    ofn = OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
    ofn.lpstrFilter = filt or "所有文件 (*.*)\0*.*\0\0"
    ofn.lpstrFile = ctypes.cast(buf, wintypes.LPWSTR)
    ofn.nMaxFile = 1024
    ofn.lpstrTitle = title
    ofn.lpstrInitialDir = initial or None
    # FILEMUSTEXIST | PATHMUSTEXIST | EXPLORER | NOCHANGEDIR
    ofn.Flags = 0x00001000 | 0x00000800 | 0x00080000 | 0x00000008
    ok = ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(ofn))
    return buf.value if ok else ""


class ReportError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code
        self.msg = msg


def data_url_candidates(report_url):
    """从报告页 URL 里取出 data 参数，解析成候选绝对地址（按优先级）。

    允许三种写法：绝对 https://…、根相对 /report/xxx.json、路径相对 report/xxx.json。
    相对路径先按页面所在目录解析，再补一个根相对的兜底（Mortal 两种都出现过）。
    """
    u = urlparse(report_url or "")
    if u.scheme not in ("http", "https") or (u.hostname or "") not in ALLOWED_HOSTS:
        raise ReportError("REPORT_URL_INVALID", f"报告页地址不在允许范围：{report_url}")
    data = (parse_qs(u.query).get("data") or [""])[0].strip()
    if not data:
        raise ReportError("NO_DATA_PARAM", "报告页地址里没有 data 参数")
    cands = [urljoin(report_url, data)]
    if not data.startswith("/") and not re.match(r"^[a-z][a-z0-9+.-]*:", data, re.I):
        alt = f"https://{u.hostname}/" + data.lstrip("./")
        if alt not in cands:
            cands.append(alt)
    out = []
    for c in cands:
        v = urlparse(c)
        if v.scheme != "https" or (v.hostname or "") not in ALLOWED_HOSTS:
            raise ReportError("DATA_HOST_BLOCKED", f"报告数据地址被拒绝：{c}")
        out.append(c)
    return out


def resolve_data_url(report_url):
    return data_url_candidates(report_url)[0]


def proxy_env():
    """当前进程会用的代理（环境变量优先，Windows 再看注册表）。"""
    import urllib.request
    try:
        return {k: v for k, v in (urllib.request.getproxies() or {}).items() if v}
    except Exception:
        return {}


def friendly_net_error(e, url=""):
    """把 WinError / ssl 报错翻成能照做的中文，别只甩一串 10061。"""
    s = f"{type(e).__name__}: {e}"
    if "10061" in s or "refused" in s.lower() or "拒绝" in s:
        hint = ("连接被拒绝 —— 多半是本机代理没开：系统或环境变量里配了 HTTP(S)_PROXY，"
                "但那个端口没人监听。把代理打开，或清掉这两个环境变量再试。")
    elif "10060" in s or "timed out" in s.lower() or "超时" in s:
        hint = "连接超时 —— 到 mjai.ekyu.moe 的网络不通，可能需要开代理。"
    elif "11001" in s or "getaddrinfo" in s.lower() or "Name or service" in s:
        hint = "域名解析失败 —— 检查 DNS / 网络，或看看 hosts 里有没有把 mjai.ekyu.moe 指到 127.0.0.1。"
    elif "CERTIFICATE" in s or "SSL" in s:
        hint = "证书校验失败 —— 可能被代理或防火墙做了中间人，换网络或关掉 HTTPS 解密再试。"
    else:
        hint = ""
    px = proxy_env()
    extra = f"；当前代理 {px}" if px else "；当前没走代理"
    addr = url if len(url) <= 110 else url[:107] + "…"
    return f"{e}" + (f"（{hint}）" if hint else "") + f" 地址：{addr}{extra}"


def http_get(url, timeout=60):
    """GET 一次，返回 (status, content_type, payload, 是否走了代理)。

    先按系统 / 环境变量里的代理走，失败再**直连**重试一次。换机器最常见的坑：
    环境里留着 HTTPS_PROXY=127.0.0.1:7890 而那个代理没启动 —— urllib 立刻抛
    WinError 10061，Chrome 却不读环境变量（照样能提交），于是表现成
    「牌谱提交成功了，报告却下载不下来」。
    """
    import urllib.error
    import urllib.request

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json,text/plain,*/*",
    }
    last = None
    for use_proxy in (True, False):
        opener = urllib.request.build_opener(
            *([] if use_proxy else [urllib.request.ProxyHandler({})]))
        try:
            with opener.open(urllib.request.Request(url, headers=headers), timeout=timeout) as f:
                return (getattr(f, "status", 200),
                        (f.headers.get("Content-Type") or "").lower(),
                        f.read(), use_proxy)
        except urllib.error.HTTPError:
            raise                          # HTTP 层错误（4xx/5xx）跟代理无关，直接上报
        except Exception as e:
            last = e
    raise last


def fetch_report(data_urls):
    """下载并校验报告，返回 (text, info)。多候选地址依次尝试，全失败才报错。"""
    import urllib.error

    if isinstance(data_urls, str):
        data_urls = [data_urls]
    last = None
    for data_url in data_urls:
        try:
            status, ctype, payload, _via = http_get(data_url)
        except urllib.error.HTTPError as e:
            last = ReportError("REPORT_DOWNLOAD_FAILED", f"下载报告失败：HTTP {e.code} {data_url}")
            continue
        except Exception as e:
            last = ReportError("REPORT_DOWNLOAD_FAILED",
                               f"下载报告失败：{friendly_net_error(e, data_url)}")
            continue

        if status != 200:
            last = ReportError("REPORT_DOWNLOAD_FAILED", f"下载报告失败：HTTP {status}")
            continue
        if payload[:1] not in (b"{", b"[") and "json" not in ctype and "text" not in ctype:
            last = ReportError("REPORT_SCHEMA_INVALID",
                               f"返回的不是 JSON（Content-Type={ctype or '空'}，{len(payload)} 字节）")
            continue
        try:
            text = payload.decode("utf-8-sig")
            doc = json.loads(text)
            return text, validate_report(doc)
        except ReportError as e:
            last = e
            continue
        except Exception as e:
            last = ReportError("REPORT_SCHEMA_INVALID", f"报告不是合法 JSON：{e}")
            continue
    raise last or ReportError("REPORT_DOWNLOAD_FAILED", "下载报告失败")


def validate_report(doc):
    """报告结构校验：必须有 mjai_log（或 review.mjai_log）且 review.kyokus 是数组。"""
    if not isinstance(doc, dict):
        raise ReportError("REPORT_SCHEMA_INVALID", "报告顶层不是对象")
    rev = doc.get("review")
    log = doc.get("mjai_log") or (rev or {}).get("mjai_log")
    if not isinstance(log, list) or not log:
        raise ReportError("REPORT_SCHEMA_INVALID", "报告里没有 mjai_log（不是 Mortal 报告？）")
    if not isinstance(rev, dict):
        raise ReportError("REPORT_SCHEMA_INVALID", "报告里没有 review")
    kyokus = rev.get("kyokus")
    if not isinstance(kyokus, list) or not kyokus:
        raise ReportError("REPORT_SCHEMA_INVALID", "review.kyokus 为空，Mortal 没有给出评分")
    for k in kyokus:
        if not isinstance(k.get("entries"), list):
            raise ReportError("REPORT_SCHEMA_INVALID", "review.kyokus[*].entries 不是数组")
    seat = doc.get("player_id")
    if seat is None:
        seat = rev.get("player_id")
    if not isinstance(seat, int) or not (0 <= seat <= 3):
        raise ReportError("REPORT_SCHEMA_INVALID", f"player_id 非法（{seat!r}），无法确定复盘座次")
    return {
        "events": len(log),
        "reviewed": rev.get("total_reviewed"),
        "matches": rev.get("total_matches"),
        "rating": rev.get("rating"),
        "kyokus": len(kyokus),
        "seat": seat,
        "model": rev.get("model_tag") or "",
    }


class Api:
    """暴露给页面 JS 的接口，页面里通过 window.pywebview.api.xxx 调用。"""

    def __init__(self):
        self.port = 0
        # 独占操作的**唯一**互斥：分析、删除一局、保存设置（含切库）都必须先拿到它。
        # pywebview 的 API 请求是并发的 —— 以前删除只拿这把锁、设置只看 self.busy，
        # 于是删除进行到一半切库，前半段删的是 A 库、后半段写的是 B 库（第四轮审计 P1）。
        # 非可重入：持有期间绝不能再调用会重复获取它的方法（所以 set_settings 拆成
        # 外层拿锁的 set_settings + 内层不碰锁的 _set_settings_locked）。
        self._lock = threading.Lock()
        self._op = ""           # 当前独占操作的中文名，空串=空闲；用来告诉用户「在忙什么」
        self.busy = False       # 等价于 bool(self._op)，保留旧名字给已有调用方看
        self._chrome_proc = None
        self._owns_chrome = False
        # 人工验证期间要保留的东西：脚本进程、待续任务、以及「别关浏览器」标志
        self._node_proc = None
        self._pending = {}
        self._keep_chrome = False
        atexit.register(self.close_owned_chrome)

    def _begin_op(self, name):
        """尝试进入独占操作。拿不到锁返回 False，调用方回一句人话就要收手。"""
        if not self._lock.acquire(blocking=False):
            return False
        self._op = name
        self.busy = True
        return True

    def _end_op(self):
        self._op = ""
        self.busy = False
        self._lock.release()

    def _op_busy_msg(self, then="再试"):
        return f"正在{self._op or '处理别的请求'}，等它结束{then}"

    # ---------- 状态与依赖 ----------
    def env_report(self):
        probs = env_problems()
        return {"ok": not probs, "problems": probs,
                "python": PY or "(未找到)", "node": NODE or "(未找到)",
                "chrome": CHROME or "(未找到)",
                "webview2": (WEBVIEW2 or WEBVIEW2_SYS or "(未找到)"),
                "root": str(APP_ROOT), "library": str(LIB),
                "config": str(config_path())}

    # ---------- 设置 ----------
    def get_settings(self):
        refresh_paths()
        return {
            "library": str(LIB),
            "library_default": str((APP_ROOT / "library").resolve()),
            "library_custom": bool((CONFIG.get("library") or "").strip()),
            "chrome": CONFIG.get("chrome") or "",
            "chrome_found": CHROME or "",
            "python": CONFIG.get("python") or "",
            "python_found": PY or "",
            "node": CONFIG.get("node") or "",
            "node_found": NODE or "",
            # 界面内核：随包固定版优先，否则系统 Evergreen（版本号 / 路径）
            "webview2_found": (WEBVIEW2 or WEBVIEW2_SYS or
                               (("系统 " + WEBVIEW2_VER) if WEBVIEW2_VER else "")),
            "show_browser": bool(CONFIG.get("show_browser")),
            "bad": CONFIG.get("bad") or dict(DEFAULT_CONFIG["bad"]),
            "ui": CONFIG.get("ui") or {},
            "app_root": str(APP_ROOT),
            "config": str(config_path()),
            "counts": self._lib_counts(),
        }

    def get_bad_points(self):
        """把库里每手的 (权重差, Q 损失) 交给页面，让设置面板按当前阈值实时算分档。
        阈值算法只在 badlevel.js 里写一份，Python 这边不复刻。"""
        refresh_paths()
        p = Path(DATA) / "bad_moves.json"
        try:
            moves = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []
        if isinstance(moves, dict):
            moves = list(moves.values())
        out = []
        for m in moves if isinstance(moves, list) else []:
            if not isinstance(m, dict):
                continue
            try:
                qa, qe = float(m.get("Q_act") or 0), float(m.get("Q_exp") or 0)
                out.append([round(abs(float(m.get("gap") or 0)), 4), round(abs(qa - qe), 3)])
            except (TypeError, ValueError):
                continue
        return out

    def _lib_counts(self):
        def n(p, pat="*"):
            try:
                return len(list(Path(p).glob(pat)))
            except Exception:
                return 0

        def games():
            """coach/*.json 里一局一份 is 读表数据；index.json 是清单、*.status.json 是状态，
            都不算局数（早先把 status 也数进去，会显示成 30 局）。"""
            try:
                return len([p for p in Path(COACH).glob("*.json")
                            if p.name != "index.json" and not p.name.endswith(".status.json")])
            except Exception:
                return 0

        size = 0
        for root, _dirs, files in os.walk(LIB) if LIB.exists() else []:
            for f in files:
                try:
                    size += (Path(root) / f).stat().st_size
                except Exception:
                    pass
        return {"games": games(),
                "reports": n(REPORT, "*.json"), "images": n(IMGS, "*.png"),
                "mb": round(size / 1048576, 1)}

    def set_settings(self, patch):
        """保存设置（含切库）。**先拿到独占锁**，否则直接拒绝。

        「看一眼 self.busy 再动手」是不够的：检查完、动手前那一刻状态会变。删除一局
        正在写 A 库时切到 B 库，删除的后半段就会写到 B（第四轮审计复现过）。所以这里
        和 submit_link / delete_game 用同一把 `_lock`，拿不到就让用户等。
        """
        if not isinstance(patch, dict):
            return {"ok": False, "msg": "参数不对"}
        if not self._begin_op("保存设置"):
            return {"ok": False, "busy": True,
                    "msg": self._op_busy_msg("改设置（含切库）")}
        try:
            return self._set_settings_locked(patch)
        finally:
            self._end_op()

    def _set_settings_locked(self, patch):
        """真正干活的部分。**调用前必须持有 self._lock**，内部不再碰这把锁。

        只允许改白名单里的字段；改库目录后立即重新绑定并确保子目录存在。

        特殊处理：库目录如果就是「程序目录下的 library」，配置里存空串 ——
        这样整个文件夹拷到另一台机器、换个盘符，仍然指向新位置（便携的关键）。

        **换库要和锁一起换**：先把目标库的锁拿到手，再写配置、再切换路径、最后放旧锁。
        以前只重新绑定路径，锁还是旧库那把手，`LIB_EXCLUSIVE` 也还是旧库的结论 ——
        于是切到一个正被别的窗口占着的库，照样能删里面的报告。
        """
        global _LIB_LOCK, LIB_EXCLUSIVE, LIB_STATE, PY, NODE, CHROME
        cfg = load_config()
        for k in ("chrome", "python", "node"):
            if k in patch:
                cfg[k] = str(patch.get(k) or "").strip()
        pre_lock = None          # (handle, 目标库)：配置写成功后才正式生效
        # 只改某个开关（比如「教程已读」的 ui）时，绝不能把库目录一起清空
        if "library" in patch:
            raw = str(patch.get("library") or "").strip()
            if raw:
                target = Path(os.path.expandvars(os.path.expanduser(raw)))
                if not target.is_absolute():
                    target = APP_ROOT / target
                target = target.resolve()
                if target == (APP_ROOT / "library").resolve():
                    raw = ""
                else:
                    try:
                        target.mkdir(parents=True, exist_ok=True)
                        t = target / ".mc_write_test"
                        t.write_text("x", encoding="utf-8")
                        t.unlink()
                    except Exception as e:
                        return {"ok": False, "msg": f"这个目录不可写：{e}"}
                    raw = str(target)
            want = resolve_library({"library": raw})
            if want.resolve() != Path(LIB).resolve():
                status, h = _acquire(want)
                if status != "ok":
                    why = ("这个库正被另一个 Mortal Coach 使用"
                           if status == "busy" else
                           "这个库里建不出锁文件（权限不足或只读位置）")
                    return {"ok": False, "stale": True,
                            "msg": f"{why}：{want}\n没有切换，也没有写配置。"
                                   "关掉占用它的窗口，或换一个目录。"}
                pre_lock = (h, want)
            elif not LIB_EXCLUSIVE:
                # 同一个库：顺手再试一次，别人关掉窗口后不必重启应用才能恢复写入
                status, h = _acquire(want)
                if status == "ok":
                    pre_lock = (h, want)
            cfg["library"] = raw
        if "show_browser" in patch:
            cfg["show_browser"] = bool(patch.get("show_browser"))
        if isinstance(patch.get("bad"), dict):
            # 深合并：只提交 thresh / gap / loss 里的一部分时，其余保持原值
            cur = norm_bad(cfg.get("bad"))
            src = patch["bad"]
            merged = {
                "thresh": cur["thresh"],
                "gap": dict(cur["gap"]),
                "loss": dict(cur["loss"]),
            }
            if "thresh" in src:
                merged["thresh"] = src["thresh"]
            for key in ("gap", "loss"):
                if isinstance(src.get(key), dict):
                    for k in ("severe", "medium"):
                        if k in src[key]:
                            merged[key][k] = src[key][k]
            cfg["bad"] = norm_bad(merged)
        if isinstance(patch.get("ui"), dict):
            u = dict(cfg.get("ui") or {})
            u.update({str(k): v for k, v in patch["ui"].items()})
            cfg["ui"] = u
        p = save_config(cfg)
        if not p:
            if pre_lock and hasattr(pre_lock[0], "close"):
                pre_lock[0].close()          # 配置没写成，新锁也退回去，状态不变
            return {"ok": False, "msg": "配置写不进去（程序目录只读？）"}
        if pre_lock:
            # 先发布新锁，再放旧锁：中间不留「两边都没锁」的窗口
            unlock_library()
            _LIB_LOCK, LIB_EXCLUSIVE, LIB_STATE = pre_lock[0], True, "ok"
            if PATHS:
                PATHS.stamp_lock_owner(pre_lock[1])
        refresh_paths()
        ensure_library()
        PY, NODE, CHROME = find_py(), find_node(), find_chrome()
        return {"ok": True, "msg": "已保存", "settings": self.get_settings()}

    def _native_pick(self, kind):
        """调 Windows 原生选择框（纯 ctypes，不依赖 tkinter / .NET / COM 包装）。

        tkinter 在精简版 Python 里经常没有 `_tkinter`（随包 runtime 就是这样），
        pywebview 的 dialog 又要求把 Window 挂到 js_api 上（会让注入卡死），
        所以这里直接用 shell32 / comdlg32。
        """
        if os.name != "nt":
            return ""
        try:
            if kind == "folder":
                return _pick_folder_win("选择牌谱库目录", str(LIB))
            return _pick_file_win("选择浏览器", str(LIB),
                                  "可执行文件 (*.exe)\0*.exe\0所有文件 (*.*)\0*.*\0\0")
        except Exception as e:
            raise ReportError("PICK_FAILED", f"打不开选择框：{e}")

    def pick_library(self):
        """弹出系统选文件夹对话框；没有 GUI 环境就返回空。"""
        try:
            d = self._native_pick("folder")
            return {"ok": bool(d), "path": d or ""}
        except ReportError as e:
            return {"ok": False, "msg": e.msg}

    def pick_browser(self):
        try:
            f = self._native_pick("file")
            return {"ok": bool(f), "path": f or ""}
        except ReportError as e:
            return {"ok": False, "msg": e.msg}

    def open_library(self):
        ensure_library()
        try:
            os.startfile(str(LIB))          # noqa: S606  (Windows)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def game_status(self, tag):
        p = COACH / f"{tag}.status.json"
        if not p.exists():
            return {"ok": False, "msg": "没有状态文件"}
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception as e:
            return {"ok": False, "msg": f"状态文件读不出来：{e}"}

    # ---------- Chrome ----------
    def ensure_chrome(self):
        """复盘要一个带界面的浏览器来拿 Turnstile token。

        窗口默认挪到屏幕外（用户看不到，也不抢焦点）；设置里可以改成显示，
        方便自己处理验证码。关闭走 CDP Browser.close，profile 干净、不会弹崩溃恢复。

        **只用自己启动的实例**：端口交给浏览器自己挑（--remote-debugging-port=0），
        从 profile 的 DevToolsActivePort 读回来。不探测也不复用系统里已有的调试端口——
        「9222 能连上」只说明有人占着那个端口，连上去等于接管别人的浏览器。
        """
        global CDP_PORT

        # 本次已经启动过、进程还活着：直接复用（端口就是当初那个）
        if (self._owns_chrome and self._chrome_proc is not None
                and self._chrome_proc.poll() is None and CDP_PORT and port_open(CDP_PORT)):
            return True

        cands = chrome_candidates()
        if not cands:
            globals()["CHROME_STATE"] = "BROWSER_NOT_FOUND"
            globals()["CHROME_NOTE"] = "no chromium-based browser found"
            return False

        # profile 按**本副本**分开，不放在 LIB 里：两个实例可能指向同一个
        # 网盘/移动盘上的库，共用 profile 会互相删对方的 DevToolsActivePort，
        # 甚至同时写坏 cookies。放实例目录后各自独立。
        prof = prepare_profile(instance_dir() / "chrome-profile")
        repair_chrome_prefs(prof)
        # 上一轮留下的端口文件会让我们读到过期端口，先删掉
        try:
            (Path(prof) / "DevToolsActivePort").unlink()
        except OSError:
            pass
        pos = "0,0" if CONFIG.get("show_browser") else "-32000,-32000"

        # 路径存在 ≠ 能跑：残缺安装、被组策略拦、指向已删目录的快捷方式都见过。
        # 所以逐个**试启动**，最多 3 个候选；一旦调试端口通了就固定下来，绝不
        # 在人工验证中途换内核（换内核 = 换浏览器身份，验证进度全丢）。
        port = 0
        skipped = []
        for cand, src in cands[:3]:
            try:
                self._chrome_proc = subprocess.Popen(
                    [cand, "--remote-debugging-port=0",
                         f"--user-data-dir={prof}",
                         f"--window-position={pos}", "--window-size=1000,760",
                         "--no-first-run", "--no-default-browser-check",
                         "--disable-session-crashed-bubble", "--hide-crash-restore-bubble",
                         "--disable-restore-session-state", "--disable-background-mode",
                         "--noerrdialogs", "--disable-breakpad", "--no-service-autorun",
                         "--disable-translate", "--lang=zh-CN",
                         # 窗口在屏幕外时 Chrome 会把后台页面的定时器降频，人机验证
                         # 的轮询一慢就更拿不到 token —— 这几个开关一起关掉。
                         "--disable-background-timer-throttling",
                         "--disable-renderer-backgrounding",
                         "--disable-backgrounding-occluded-windows",
                         "--disable-features=CalculateNativeWinOcclusion,Translate,MediaRouter",
                         "https://mjai.ekyu.moe/"], **gui_process_kwargs())
                self._owns_chrome = True
                CDP_PORT = 0
            except Exception as e:
                skipped.append("%s: cannot start (%s)" % (Path(cand).name, type(e).__name__))
                self._chrome_proc = None
                self._owns_chrome = False
                continue
            got = 0
            for _ in range(80):
                time.sleep(0.25)
                got = read_devtools_port(prof)
                if got and port_open(got):
                    break
                if self._chrome_proc.poll() is not None:
                    break
            if got and port_open(got):
                port = got
                globals()["CHROME"] = cand
                globals()["CHROME_SOURCE"] = src
                globals()["CHROME_NOTE"] = ("; ".join(skipped) + "; " if skipped else "") + "using " + src
                break
            skipped.append("%s: devtools port never came up" % Path(cand).name)
            try:
                self._chrome_proc.kill()
            except Exception:
                pass
            self._chrome_proc = None
            self._owns_chrome = False
            try:
                (Path(prof) / "DevToolsActivePort").unlink()
            except OSError:
                pass
        if not port:
            globals()["CHROME_STATE"] = "BROWSER_START_FAILED"
            globals()["CHROME_NOTE"] = "; ".join(skipped)[:300]
            return False
        CDP_PORT = port

        # 第二步：真的有页面可用。端口通但 target 还没建出来时，
        # submit_auto 会以为是空浏览器直接 NO_PAGE —— 那其实是「还没好」，不是「坏了」。
        for _ in range(40):
            if cdp_page_targets(port):
                globals()["CHROME_STATE"] = "PAGE_READY"
                globals()["CHROME_VER"] = cdp_browser_version(port)
                return True
            if self._chrome_proc.poll() is not None:
                break
            time.sleep(0.25)
        # 一个页面都没有：让浏览器自己开一个（新版本 Chrome 要求 PUT）
        try:
            import urllib.parse as _up
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/json/new?{_up.quote('https://mjai.ekyu.moe/', safe='')}",
                method="PUT")
            urllib.request.urlopen(req, timeout=5).read()
        except Exception:
            pass
        for _ in range(20):
            if cdp_page_targets(port):
                globals()["CHROME_STATE"] = "PAGE_CREATED"
                globals()["CHROME_VER"] = cdp_browser_version(port)
                return True
            time.sleep(0.25)
        globals()["CHROME_STATE"] = "PAGE_LOAD_FAILED"
        globals()["CHROME_VER"] = cdp_browser_version(port)
        return False

    def close_owned_chrome(self):
        global CDP_PORT
        p = self._chrome_proc
        if not self._owns_chrome or p is None:
            return
        self._chrome_proc = None
        self._owns_chrome = False
        try:
            if p.poll() is None:
                cdp_browser_close(CDP_PORT)      # 先礼后兵：让它自己正常退出（只关自己的端口）
                try:
                    p.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    p.terminate()
                    p.wait(timeout=4)
        except Exception:
            try:
                if p.poll() is None:
                    p.kill()
            except Exception:
                pass
        finally:
            CDP_PORT = 0

    def _logfile(self, tag):
        LOGS.mkdir(parents=True, exist_ok=True)
        return LOGS / f"{tag}.log"

    # ---------- 提交脚本：逐行读、实时发布 ----------
    def _run_submit_node(self, cfg, logs, tag):
        """跑外置提交脚本，边跑边把阶段发布给前端。

        以前是 subprocess.run(capture_output=True)：脚本跑完才拿到全部输出，
        于是「请点一下验证码」这种需要用户当下就知道的提示，要等三分钟失败后
        才会出现在结果里。改成 Popen + 逐行读之后，NEED_MANUAL 一出现就能显示。
        """
        import queue as _queue
        proc = subprocess.Popen([NODE, str(TOOLS / "submit_auto.mjs"), cfg],
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace",
                                cwd=str(TOOLS), env=child_env(),
                                **hidden_process_kwargs())
        self._node_proc = proc
        q = _queue.Queue()

        def reader():
            try:
                for ln in proc.stdout:
                    q.put(ln.rstrip("\r\n"))
            except Exception:
                pass
            q.put(None)

        threading.Thread(target=reader, daemon=True).start()
        lines = []
        deadline = time.time() + 1200
        saw_build = ""
        try:
            while True:
                try:
                    ln = q.get(timeout=0.5)
                except _queue.Empty:
                    if time.time() > deadline:
                        proc.kill()
                        self._write_log(tag, logs + lines + ["SUBMIT_TIMEOUT 20 分钟"])
                        raise ReportError("SUBMIT_TIMEOUT",
                                          "提交超时（20 分钟）。Mortal 那边可能排队很久，稍后再试。")
                    if proc.poll() is not None:
                        # 进程没了但队列还没读完（reader 退出前会放 None），再给一轮机会
                        try:
                            ln = q.get(timeout=1.0)
                        except _queue.Empty:
                            break
                        if ln is None:
                            break
                    else:
                        continue
                if ln is None:
                    break
                if not ln.strip():
                    continue
                lines.append(ln)
                print(ln, flush=True)
                if ln.startswith("SCRIPT_BUILD"):
                    saw_build = ln.split()[-1]
                    if saw_build.isdigit() and int(saw_build) != SUBMIT_BUILD:
                        msg = (f"WARN 提交脚本版本 {saw_build} 与程序期望的 {SUBMIT_BUILD} 不一致："
                               "旧脚本配新程序（或反过来）会出现「设置改了不生效」，请用同一版本重新发布")
                        lines.append(msg)
                        print(msg, flush=True)
                    submit_state_set(stage="STARTING")
                    continue
                stage = submit_stage_of(ln)
                if stage:
                    submit_state_set(stage=stage)
                if ln.startswith("NEED_MANUAL"):
                    submit_state_set(detail=ln[len("NEED_MANUAL"):].strip())
                elif ln.startswith("TOKEN_WAIT"):
                    parts = ln.split()
                    if len(parts) >= 3 and parts[2].endswith("s"):
                        try:
                            submit_state_set(wait=int(parts[2][:-1]))
                        except ValueError:
                            pass
                elif ln.startswith("VERIFICATION_TIMEOUT"):
                    submit_state_set(resumable=True)
                elif ln.startswith("VERIFICATION_FAILED"):
                    submit_state_set(detail="验证失败，可重新加载验证或改用普通浏览器",
                                     resumable=True)
        finally:
            self._node_proc = None
            try:
                if proc.poll() is None:
                    proc.kill()
            except Exception:
                pass
        logs += ["--- submit_auto ---"] + lines
        return "\n".join(lines)

    # ---------- 给前端用的三个入口 ----------
    def get_submit_status(self):
        """前端轮询：Promise 还没返回时也能知道现在卡在哪一步。"""
        st = submit_state_get()
        st.update({"app_build": build_id(), "submit_build": SUBMIT_BUILD,
                   "browser": CHROME or "", "browser_state": CHROME_STATE,
                   "browser_version": CHROME_VER, "browser_source": CHROME_SOURCE,
                   "browser_note": CHROME_NOTE,
                   "show_browser": bool(CONFIG.get("show_browser"))})
        return st

    def show_verification_browser(self):
        """把**本应用启动的**浏览器窗口显示出来、置前，并切到 Mortal 标签。

        只操作自己那个 PID 的窗口，不去搜索/接管用户日常浏览器。

        「显示成功」不能只看 ShowWindow 的返回：窗口可能被最小化到托盘、位置
        还在屏幕外（-32000）、或被系统隐藏。最后用 IsWindowVisible + 屏幕内
        矩形双重确认，做不到就如实返回失败，让前端给出可操作的提示。
        """
        p = self._chrome_proc
        if not (self._owns_chrome and p is not None and p.poll() is None):
            return {"ok": False, "msg": "验证用的浏览器没有在运行。点「分析」重新开始。"}
        if os.name != "nt":
            return {"ok": False, "msg": "只有 Windows 支持显示验证窗口"}
        try:
            hwnd = find_window_by_pid(p.pid)
            if not hwnd:
                return {"ok": False, "msg": "没找到浏览器窗口（可能已最小化到托盘）"}
            u32 = ctypes.windll.user32
            u32.ShowWindow(hwnd, 9)                       # SW_RESTORE
            u32.ShowWindow(hwnd, 5)                       # SW_SHOW：被隐藏过也能拉回来
            rect = wintypes.RECT()
            u32.GetWindowRect(hwnd, ctypes.byref(rect))
            sw, sh = u32.GetSystemMetrics(0), u32.GetSystemMetrics(1)
            # 窗口在屏幕外（-32000）时搬回可见位置
            if rect.left <= -1000 or rect.top <= -1000:
                u32.SetWindowPos(hwnd, 0, 60, 40, 1120, 820, 0x0040)
            elif rect.right > sw + 40 or rect.bottom > sh + 40:
                u32.SetWindowPos(hwnd, 0, 40, 30, min(1200, sw - 80), min(860, sh - 80), 0x0040)
            u32.SetForegroundWindow(hwnd)
            u32.BringWindowToTop(hwnd)
            # 切到 Mortal 那个标签：多标签时用户看到别的页，验证框等于没露面
            try:
                rows = cdp_json(CDP_PORT, "/json/list") or []
                t = [x for x in rows if x.get("type") == "page"
                     and "mjai.ekyu.moe" in (x.get("url") or "")]
                if t:
                    cdp_json(CDP_PORT, "/json/activate/" + str(t[0].get("id") or ""))
            except Exception:
                pass
            if not u32.IsWindowVisible(hwnd):
                return {"ok": False, "msg": "浏览器窗口没能显示出来（可能被系统隐藏或被安全软件拦住了）"}
            u32.GetWindowRect(hwnd, ctypes.byref(rect))
            if rect.left <= -1000 or rect.top <= -1000:
                return {"ok": False, "msg": "浏览器窗口还在屏幕外，没能搬到可见位置"}
            return {"ok": True, "msg": "已把验证窗口放到前面", "visible": True,
                    "rect": [rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top]}
        except Exception as e:
            return {"ok": False, "msg": f"显示窗口失败：{e}"}

    def open_verification_page(self):
        """设置里点「打开验证页面」：启动（或复用）本应用的浏览器并显示出来。

        用途是先确认「浏览器能开、页面能加载、验证框能点」，不用真的提交一局。
        """
        if not (self._owns_chrome and self._chrome_proc is not None
                and self._chrome_proc.poll() is None and CDP_PORT
                and port_open(CDP_PORT)):
            if not self.ensure_chrome():
                return {"ok": False, "msg": "没能启动浏览器：" + (CHROME_STATE or "未知原因")}
        self._keep_chrome = True      # 单独打开的窗口不随任务收尾关闭
        r = self.show_verification_browser()
        r["browser"] = CHROME
        r["version"] = CHROME_VER
        return r

    def cancel_submit(self):
        """用户主动取消：停掉脚本、关掉本应用启动的浏览器。"""
        proc = self._node_proc
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass
        self._node_proc = None
        self._keep_chrome = False
        self._pending = {}
        self.close_owned_chrome()
        submit_state_set(active=False, stage="CANCELLED", detail="已取消",
                         resumable=False)
        return {"ok": True, "msg": "已取消这次提交"}


    def _write_log(self, tag, lines):
        try:
            self._logfile(tag).write_text("\n".join(lines), encoding="utf-8")
        except Exception:
            pass

    # ---------- 主流程 ----------
    def submit_link(self, url, fmt="auto", model="4.1b", seat=""):
        """粘贴链接 → Mortal 报告 → 逐手解读。返回带阶段与状态的结果。

        stage 依次为：VALIDATING_INPUT → CHROME_READY → SUBMITTED → REPORT_URL_READY
                      → REPORT_DOWNLOADED → REPORT_VALIDATED → EXTRACTING/EXPLAINING
                      → COACH_EXPORTING → READY
        需要人工点验证码时返回 status=verification_pending（可续），
        这时**浏览器不关**，用户点「继续等待」走 resume_submit() 接着等。
        """
        return self._submit_guarded(url, fmt, model, seat, tag=None, resume=False)

    def resume_submit(self):
        """继续等待人工验证：同一浏览器、同一页面、同一个标签，不重新开始。"""
        return self._resume_verification(False)

    def retry_verification(self):
        """用户主动要求重载验证；仅允许没有在提交的待验证任务。"""
        return self._resume_verification(True)

    def request_verification_reload(self):
        """通知正在等验证的脚本重载；脚本在提交前再次核对页面。"""
        st = submit_state_get()
        proc = self._node_proc
        if (not st.get("active") or st.get("stage") != "AWAITING_VERIFICATION"
                or proc is None or proc.poll() is not None or proc.stdin is None):
            return {"ok": False, "msg": "当前不在等待验证；请稍后重试，提交或评分期间不能重载。"}
        try:
            proc.stdin.write("reload-verification\n")
            proc.stdin.flush()
            return {"ok": True, "msg": "已请求重新加载验证；请在浏览器中完成验证。"}
        except (OSError, ValueError):
            return {"ok": False, "msg": "验证任务已经结束，请使用「重新加载验证」重试。"}

    def _resume_verification(self, reload_page):
        p = self._pending or {}
        if not p:
            return {"ok": False, "status": "failed", "stage": "NO_PENDING",
                    "msg": "没有在等待验证的任务，点「分析」重新开始这一次。"}
        if not (self._owns_chrome and self._chrome_proc is not None
                and self._chrome_proc.poll() is None and CDP_PORT
                and port_open(CDP_PORT)):
            self._pending = {}
            return {"ok": False, "status": "failed", "stage": "BROWSER_GONE",
                    "msg": "用于验证的浏览器已经关掉了，点「分析」重新开始这一次。"}
        return self._submit_guarded(p.get("url", ""), p.get("fmt", "auto"),
                                    p.get("model", "4.1b"), p.get("seat", ""),
                                    tag=p.get("tag") or None, resume=True,
                                    reload_verification=reload_page)

    def open_official_review(self, url=""):
        """在用户默认浏览器打开官网，沿用其正常浏览环境；不读取其资料。"""
        if not self._begin_op("切换到普通浏览器"):
            return {"ok": False, "msg": "请先取消当前分析，再切换到普通浏览器。"}
        try:
            value = normalize_pasted_input(url)
            target = "https://mjai.ekyu.moe/"
            if re.match(r"^https?://", value, re.I):
                from urllib.parse import urlencode
                target += "?" + urlencode({"url": value})
            # 用户明确选择切换路径，停止旧的待验证任务，避免两个入口同时提交。
            self.cancel_submit()
            import webbrowser
            if not webbrowser.open(target, new=2):
                return {"ok": False, "msg": "未能打开默认浏览器，请手动打开 https://mjai.ekyu.moe/"}
            return {"ok": True, "msg": "已打开普通浏览器。请核对模型和座次并生成报告，再复制最终报告页地址回到输入框，点「分析」。"}
        except Exception as e:
            return {"ok": False, "msg": f"打开普通浏览器失败：{e}"}
        finally:
            self._end_op()

    def _submit_guarded(self, url, fmt, model, seat, tag=None, resume=False,
                        reload_verification=False):
        if not LIB_EXCLUSIVE:
            # 不能直接 raise：这是在 try 之外，前端只会看到一个没有 stage 的失败，
            # 页面显示不出「该干什么」。统一返回结构化结果。
            return {"ok": False, "status": "failed", "stage": "LIB_BUSY", "error_code": "LIB_BUSY",
                    "msg": lib_busy_msg()}
        # 与分析、删除、保存设置共用同一把独占锁：拿到就独占整个库上下文直到收尾
        if not self._begin_op("分析这一局"):
            return {"ok": False, "status": "failed", "stage": "BUSY",
                    "msg": ("上一局还在分析，等它跑完" if self._op == "分析这一局"
                            else self._op_busy_msg("分析"))}
        self._keep_chrome = False
        # 先把上一轮的状态清干净：否则续等时会闪一下上次的「已等 45s」和旧阶段
        submit_state_reset((self._pending or {}).get("tag", ""))
        try:
            return self._submit(url, fmt, model, seat, tag=tag, resume=resume,
                                reload_verification=reload_verification)
        except ReportError as e:
            out = {"ok": False, "status": "failed", "stage": e.code,
                   "msg": e.msg, "error_code": e.code}
            if e.code in ("VERIFICATION_PENDING", "VERIFICATION_FAILED"):
                # 不是失败：验证还没做完。浏览器、profile、页面全部留着，
                # 用户点「继续等待」就在同一页面上接着等。
                out.update({"status": ("verification_failed" if e.code == "VERIFICATION_FAILED"
                                       else "verification_pending"), "resumable": True,
                            "tag": (self._pending or {}).get("tag", ""),
                            "wait": (self._pending or {}).get("waited", 0),
                            "browser": CHROME or "", "browser_state": CHROME_STATE})
            return out
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "status": "failed", "stage": "UNEXPECTED",
                    "msg": f"{type(e).__name__}: {e}"}
        finally:
            if not self._keep_chrome:
                self.close_owned_chrome()
                self._pending = {}
            self._end_op()
            submit_state_set(active=False)

    def _submit(self, url, fmt, model, seat, tag=None, resume=False,
                reload_verification=False):
        logs = []
        t0 = time.time()

        def say(s):
            line = f"[{time.strftime('%H:%M:%S')}] {s}"
            logs.append(line)
            print(line, flush=True)
            return line

        url = normalize_pasted_input(url)
        if not url:
            raise ReportError("INPUT_INVALID", "链接 / 对局 ID 为空")
        if len(url) < 8:
            raise ReportError("INPUT_INVALID", "内容太短，不像牌谱")
        direct_candidate = bool(report_data_candidates_from_input(url))
        missing = env_problems()
        if direct_candidate:
            missing = [x for x in missing if "Chrome" not in x and "Node" not in x]
        if missing:
            raise ReportError("ENV_INCOMPLETE", "；".join(missing))
        say(f"VALIDATING_INPUT format={fmt} model={model} seat={seat or 'auto'}")
        say(f"NET_INFO proxy={proxy_env() or '直连'}")

        fmt = guess_format(url, fmt)
        direct_candidate = bool(report_data_candidates_from_input(url))
        if direct_candidate:
            fmt = "log-url"
        model = model if model in MODELS else "4.1b"
        seat = str(seat if seat not in (None, "") else "")
        if seat and seat not in ("0", "1", "2", "3"):
            seat = ""
        if fmt != "log-url" and not direct_candidate and not seat:
            seat = seat_from_log_id(url)          # 一番街 / 姬麻将：@N 即座位
        if fmt != "log-url" and not direct_candidate and not seat:
            raise ReportError("INPUT_INVALID",
                              "非链接形式的牌谱必须指定座次（东起=0 / 南起=1 / 西起=2 / 北起=3）")
        if fmt == "riichi-city-log-id" and "@" not in url:
            url = url + ("@" + seat if seat else "")
        say(f"格式 {fmt} · 模型 {model} · 座位 {seat or '自动识别'}")
        say(f"牌谱地址 {url}")

        # 链接形式先看一眼主机：Mortal 只认雀魂 / 天凤的牌谱地址，
        # 明显不是的（牌谱屋、视频站…）当场说清楚，别让用户等三次重试才被告知。
        if fmt == "log-url" and not direct_candidate and re.match(r"^https?://", url, re.I):
            host = (urlparse(url).hostname or "").lower()
            if host and not any(k in host for k in
                                ("tenhou", "maj-soul", "mahjongsoul", "majsoul", "yo-star", "ekyu.moe")):
                raise ReportError(
                    "INPUT_INVALID",
                    f"Mortal 只认雀魂（game.maj-soul.com / mahjongsoul）和天凤（tenhou.net）的牌谱链接，"
                    f"这个地址是 {host}。请在游戏里「分享牌谱」复制链接再来。")

        direct_data = report_data_candidates_from_input(url)
        if not tag:
            tag = next_tag(time.strftime("%y%m%d") if direct_data else tag_from_url(url))
        submit_state_reset(tag)
        say(f"BUILD {build_id()} · submit_script_build {SUBMIT_BUILD}")
        if direct_data:
            say("检测到 Mortal 报告链接，直接下载报告")
            data_urls = direct_data
            report_url = url
        else:
            data_urls = None
            report_url = ""

        if not direct_data:
            if resume:
                submit_state_set(stage="AWAITING_VERIFICATION", detail="继续等待验证")
                say(f"RESUME 沿用同一个浏览器（port {CDP_PORT}）")
            else:
                submit_state_set(stage="BROWSER_STARTING", detail="正在启动浏览器")
                if not self.ensure_chrome():
                    raise ReportError(
                        "BROWSER_START_FAILED",
                        ("没能启动复盘用的浏览器" if CHROME_STATE != "PAGE_LOAD_FAILED"
                         else "浏览器启动了但没有可用页面（可能被安全软件拦截）")
                        + "。请确认装了 Chrome / Edge（或在其设置里指定路径）后再试。")
                say(f"CHROME_READY {Path(CHROME).name if CHROME else 'chrome'} · port {CDP_PORT}"
                    f" · {CHROME_STATE or 'PAGE_READY'} · {CHROME_SOURCE or '-'}"
                    f" · {CHROME_VER or '版本未知'} · {CHROME or '-'}")
            # 页面是否停留在 about:blank 不由 Python 判断：交给脚本 gotoHome，
            # 它会等到表单真的出现，失败时明确输出 PAGE_LOAD_FAILED。
            cfg = json.dumps({"url": url, "format": fmt, "model": model,
                              "seat": seat, "kyokus": "", "tempo": "",
                              "show": bool(CONFIG.get("show_browser")),
                              "resume": bool(resume),
                              "reload": bool(reload_verification),
                              "wait": MANUAL_WAIT_SEC}, ensure_ascii=False)
            say(f"提交到 Mortal（标签 {tag}）…")
            out = self._run_submit_node(cfg, logs, tag)

        m = re.search(r"^REPORT\s+(\S+)\s*$", out, re.M) if not direct_data else True
        if not direct_data and not m:
            self._write_log(tag, logs)
            # 人工模式超时不是失败：浏览器还开着、页面还在，可以接着等
            if "VERIFICATION_PENDING" in out:
                self._keep_chrome = True
                self._pending = {"url": url, "fmt": fmt, "model": model, "seat": seat,
                                 "tag": tag, "waited": submit_state_get().get("wait", 0)}
                failed = re.search(r"^VERIFICATION_FAILED\s+(\d{6}|unknown)\s*$", out, re.M)
                if failed:
                    code = failed.group(1)
                    submit_state_set(stage="VERIFICATION_FAILED", resumable=True)
                    raise ReportError(
                        "VERIFICATION_FAILED",
                        f"Cloudflare 验证失败（错误码 {code}）。本次尚未提交牌谱，验证窗口已保留。"
                        "可以点「重新加载验证」重试；若普通浏览器能通过，请点「使用普通浏览器生成报告」，"
                        "生成报告后将报告地址粘贴回来分析。")
                raise ReportError(
                    "VERIFICATION_PENDING",
                    "浏览器已经打开，但这次验证还没完成。"
                    "请在弹出的浏览器窗口里点一下「确认您是真人」——点完会自动继续；"
                    "如果窗口显示失败，请点「重新加载验证」；普通浏览器能通过时，也可以切换到普通浏览器生成报告。")
            if "NO_TOKEN" in out:
                raise ReportError("NO_TOKEN", no_token_hint(out, self._logfile(tag)))
            if "NO_PAGE" in out:
                raise ReportError("BROWSER_START_FAILED",
                                  "浏览器里一个可用页面都没有（启动后被立刻关掉了？）。")
            if "PAGE_LOAD_FAILED" in out:
                raise ReportError(
                    "PAGE_LOAD_FAILED",
                    "浏览器打开了，但 Mortal 首页一直没加载出表单。"
                    "多半是网络/代理拦了 mjai.ekyu.moe，或安全软件阻止了页面脚本。"
                    f"（浏览器 {CHROME_VER or '版本未知'}，日志 logs/{tag}.log）")
            if "NO_FORM" in out:
                raise ReportError("NO_REPORT_URL", "Mortal 首页表单没找到，可能官网改版了。")
            if "SUBMIT_NOT_SENT" in out:
                raise ReportError("SUBMIT_NOT_SENT",
                                  "表单没提交出去（浏览器一直停在 Mortal 首页）。"
                                  "多半是页面没加载完或人机验证拦了，再点一次「分析」。")
            pm = re.search(r"PAGE_ERROR\s+(.+)", out)
            if pm:
                txt = pm.group(1).strip()
                hint = ""
                if re.search(r"not from tenhou|not from mahjong", txt, re.I):
                    hint = ("（已自动重试 3 次。同一链接在网页版能通过、这里却报这句，"
                            "通常是 Mortal 那边抓牌谱失败 —— 隔一会儿再点一次「分析」即可。"
                            f"提交的地址：{url}）")
                elif re.search(r"player\s*id", txt, re.I):
                    hint = "（这条牌谱里没有玩家 ID，请在「复盘座次」里指定自己是东起/南起/西起/北起）"
                raise ReportError("SUBMIT_REJECTED",
                                  "Mortal 拒绝了这个牌谱：" + txt[:200] + hint)
            if "NO_REPORT_URL" in out:
                tail = re.search(r"REPORT_URL\s+(\S+)", out)
                raise ReportError("NO_REPORT_URL",
                                  "提交后没进到报告页"
                                  + (f"（停在 {tail.group(1)[:110]}）" if tail else "")
                                  + "。常见原因：链接失效 / 别人正在分析 / 人机验证过期。")
            if "REPORT_TIMEOUT" in out:
                raise ReportError("REPORT_TIMEOUT",
                                  "报告页打开了但牌桌一直没渲染完，稍等再试一次。")
            tail = ((out.strip().splitlines() or [""])[-1])[:160]
            raise ReportError("NO_REPORT_URL",
                              f"Mortal 没给出报告（最后状态：{tail}）。"
                              f"完整过程见 logs/{tag}.log")
        if not direct_data:
            report_url = m.group(1)
            say(f"REPORT_URL_READY {report_url}")
            data_urls = data_url_candidates(report_url)
        say(f"报告数据 {data_urls[0]}")
        payload, info = fetch_report(data_urls)
        say("REPORT_VALIDATED " + json.dumps(info, ensure_ascii=False))

        # 原子替换：先写临时文件再 os.replace，避免前端读到半个 JSON
        REPORT.mkdir(parents=True, exist_ok=True)
        rep = REPORT / f"{tag}.json"
        tmp = REPORT / f".{tag}.json.tmp"
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, rep)
        say(f"REPORT_DOWNLOADED {rep.name}（{len(payload)} 字节）")

        # 报告落盘后跑「单局全自动流水线」：恶手 → 中文解读 → 坐标 → coach 查表
        say("EXTRACTING / EXPLAINING …")
        status = {"ok": False, "stage": "FAILED", "error_code": "PIPELINE_FAILED",
                  "error_message": "流水线没有输出状态文件"}
        try:
            pr = subprocess.run([PY, str(SCRIPTS / "pipeline_one.py"), str(rep), tag],
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=900, cwd=str(APP_ROOT),
                                env=child_env(), **hidden_process_kwargs())
            out2 = (pr.stdout or "") + (pr.stderr or "")
            logs += ["--- pipeline_one ---"] + out2.splitlines()
            say(f"pipeline 退出码 {pr.returncode}")
        except subprocess.TimeoutExpired:
            logs += ["PIPELINE_TIMEOUT 15 分钟"]
            self._write_log(tag, logs)
            return {"ok": False, "status": "partial", "stage": "PIPELINE_TIMEOUT", "tag": tag,
                    "report": f"report/{tag}.json",
                    "msg": "解读生成超时（15 分钟）。rating 与牌桌可以看，但这一局没有逐手解读。"}

        sp = COACH / f"{tag}.status.json"
        if sp.exists():
            try:
                status = json.load(open(sp, encoding="utf-8"))
            except Exception as e:
                status = {"ok": False, "stage": "FAILED", "error_code": "STATUS_UNREADABLE",
                          "error_message": str(e)}
        self._write_log(tag, logs)
        bad = status.get("coach_moves") or status.get("entries") or 0
        head = (f"Mortal {model}" + (f" · 座位 {SEAT_CN[int(seat)]}" if seat else " · 座位自动识别"))
        base = {"tag": tag, "report": f"report/{tag}.json", "bad_moves": bad,
                "stage": status.get("stage") or "", "status": status.get("status") or "",
                "log": str(self._logfile(tag))}

        if status.get("status") == "ok":
            if CONFIG.get("show_browser"):
                # 勾了「显示浏览器」：窗口留到应用退出。同一浏览器身份 + 同一
                # 资料目录，下一局直接复用，不用重新启动、也不必重新过验证。
                self._keep_chrome = True
                self._pending = {}
            msg = (f"完成：{bad} 手解读已生成（{head}）" if bad
                   else f"完成：这一局没有超过 30pt 阈值的恶手（{head}）")
            return dict(base, ok=True, msg=msg, elapsed=round(time.time() - t0))
        if status.get("status") == "partial":
            return dict(base, ok=False,
                        msg=f"部分完成：{bad} 手有解读，另有 {status.get('explain_failed', 0)} 手生成失败。"
                            f"详情见日志 {self._logfile(tag).name}")
        return dict(base, ok=False,
                    msg="解读生成失败：" + (status.get("error_message")
                                          or status.get("error_code") or "未知原因")
                        + f"（日志 {self._logfile(tag).name}）")

    def open_game(self, tag):
        return {"ok": True, "tag": tag}

    def list_history(self):
        """返回可查看的历史牌谱摘要，日期从标签 YYMMDD 提取。"""
        out = []
        idx = COACH / "index.json"
        try:
            rows = json.loads(idx.read_text(encoding="utf-8")) if idx.exists() else []
        except Exception:
            rows = []
        for row in rows:
            tag = str(row.get("tag") or "")
            m = re.match(r"^(\d{2})(\d{2})(\d{2})", tag)
            if m:
                yy, mm, dd = map(int, m.groups())
                year = 2000 + yy
                month, day = mm, dd
                date = f"{year:04d}-{mm:02d}-{dd:02d}"
            else:
                year = month = day = 0
                date = "未知日期"
            out.append(dict(row, tag=tag, year=year, month=month, day=day, date=date))
        out.sort(key=lambda x: (x.get("date", ""), x.get("tag", "")), reverse=True)
        return out

    def delete_game(self, tag):
        """删除一局及其生成物，并重建 coach 索引。

        与分析、保存设置共用一把锁：分析途中删除会和合并 bad_moves / 重写 coach 索引
        打架，所以这里直接拒绝（排队反而让人以为没反应）。反过来，删除途中也不许切库 ——
        以前设置只看 self.busy，删除不置位，于是删除前半段在 A 库、后半段写到 B 库。
        """
        tag = str(tag or "")
        if not re.fullmatch(r"\d{6}[A-Z0-9_]*", tag):
            return {"ok": False, "msg": "局标签格式非法"}
        if not LIB_EXCLUSIVE:
            return {"ok": False, "msg": lib_busy_msg(short=True)}
        if not self._begin_op("删除这一局"):
            return {"ok": False, "msg": self._op_busy_msg("再删")}
        try:
            return self._delete_game_locked(tag)
        finally:
            self._end_op()

    def _delete_game_locked(self, tag):
        # 全程用进入时的库上下文：路径先拍成快照，后面不再反复读可变的全局变量。
        # （真正的互斥由调用方的 self._lock 保证，快照是第二道保险。）
        report, coach, data, logs, imgs = REPORT, COACH, DATA, LOGS, IMGS
        paths = [
            report / f"{tag}.json", coach / f"{tag}.json", coach / f"{tag}.status.json",
            data / "work" / f"{tag}.json", logs / f"{tag}.log",
        ]
        for p in paths:
            try:
                if p.exists(): p.unlink()
            except Exception as e:
                return {"ok": False, "msg": f"删除 {p.name} 失败：{e}"}

        # 图片在牌谱库里（LIB/img_layout），不是程序目录的 assets —— 之前写错目录，
        # 删完 PNG 还在，用户以为没删掉。
        img_failed = []
        if imgs.exists():
            for p in imgs.glob(f"{tag}_*.png"):
                try:
                    p.unlink()
                except Exception:
                    img_failed.append(p.name)
        if img_failed:
            return {"ok": False, "msg": f"有 {len(img_failed)} 张图没删掉（文件被占用？）："
                                        + "、".join(img_failed[:3])}

        bad_path = data / "bad_moves.json"
        if bad_path.exists():
            try:
                rows = json.loads(bad_path.read_text(encoding="utf-8"))
                rows = [r for r in rows if str(r.get("game") or "") != tag]
                # 原子写：中途失败也不会留下半截 JSON，把整库恶手记录弄坏
                tmp = bad_path.with_name("bad_moves.json.tmp")
                tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
                tmp.replace(bad_path)
            except Exception as e:
                return {"ok": False, "msg": f"更新恶手记录失败：{e}"}

        if PY and (SCRIPTS / "mk_coach.py").exists():
            try:
                r = subprocess.run([PY, str(SCRIPTS / "mk_coach.py")], cwd=str(APP_ROOT),
                                   capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=300,
                                   env=child_env(), **hidden_process_kwargs())
                if r.returncode != 0:
                    detail = ((r.stdout or "") + (r.stderr or "")).strip()[-300:]
                    return {"ok": False, "tag": tag,
                            "msg": "牌谱已删除，但重建历史索引失败：" + (detail or f"退出码 {r.returncode}"),
                            "partial": True}
            except Exception as e:
                return {"ok": False, "tag": tag,
                        "msg": f"牌谱已删除，但重建历史索引时报错：{type(e).__name__}: {e}",
                        "partial": True}
        return {"ok": True, "tag": tag, "history": self.list_history()}


def first_bad(tag):
    """该局第一处需要解读的坐标，用于启动时直接停在有内容的一手。"""
    p = COACH / f"{tag}.json"
    if not p.exists():
        return None
    try:
        d = json.load(open(p, encoding="utf-8"))
        ks = list(d.get("moves") or {})
        if not ks:
            return None
        h, _, pl = ks[0].partition(":")
        return int(h), int(pl)
    except Exception:
        return None


def start_url(port):
    return f"http://127.0.0.1:{port}/kd/?view=home"


def webview_storage():
    """pywebview 的持久化目录：localStorage（教程是否已读、语言、选项）要跨次启动保留。

    pywebview 默认 private_mode=True —— 每次启动换一个临时用户目录，localStorage
    全清空，于是「已经看过教程」每次都会再弹。这里关掉隐私模式并指一个稳定目录。

    目录按**程序副本**分开（instance_dir），两份 A/B 副本不共享 localStorage 与
    缓存；放用户目录而不是牌谱库，免得缓存混进「牌谱库大小」统计。
    """
    bases = [instance_dir()]
    bases.append(APP_ROOT)
    for b in bases:
        try:
            p = Path(b) / "webview"
            p.mkdir(parents=True, exist_ok=True)
            t = p / ".mc_write_test"
            t.write_text("x", encoding="utf-8")
            t.unlink()
            return str(p)
        except Exception:
            continue
    return None


def _msgbox(text, title=APP_TITLE, flags=0x4 | 0x30 | 0x10000):
    """原生提示框（不依赖 GUI 库）。返回 6=是、7=否。"""
    if os.name != "nt":
        return 7
    try:
        import ctypes
        return int(ctypes.windll.user32.MessageBoxW(None, text, title, flags))
    except Exception:
        return 7


def require_webview2():
    """没有 WebView2 就开不了窗口：先说清是什么、再说怎么装，别让用户对着
    一句 RuntimeError 发呆。装的时候给官方引导安装器（2 MB，不用重启电脑）。"""
    if WEBVIEW2_READY:
        return True
    ask = ("Mortal Coach 打开界面需要系统组件「WebView2 运行时」，这台机器上没有找到。\n\n"
           "· Windows 11 自带，正常不用管\n"
           "· Windows 10 只要装过 Microsoft Edge 一般也有\n"
           "· 确实没有的话装一次就好：约 2 MB，不用重启电脑\n\n"
           "现在打开微软官方下载页吗？（装完重新双击 mortal-coach.exe 即可）")
    if _msgbox(ask) == 6:
        try:
            import webbrowser
            webbrowser.open(WEBVIEW2_URL)
        except Exception:
            pass
    return False


def selftest():
    """机器可读自检：**不加载 GUI 依赖**，缺项返回非零退出码。

    包内 Python 只带 Pillow，没有 pywebview；把 selftest 放在 import webview 之后，
    源码模式跑 `runtime\\python\\python.exe app/main.py --selftest` 会直接崩在 import 上，
    看起来像「发行版坏了」。
    """
    if "--selftest" not in sys.argv:
        return None
    problems = env_problems()
    print(json.dumps({"app": str(APP_ROOT), "library": str(LIB),
                      "config": str(config_path()),
                      "config_writable": _can_write(Path(config_path()).parent),
                      "library_writable": _can_write(LIB),
                      "python": PY or None, "node": NODE or None,
                      "chrome": CHROME or None,
                      "chrome_source": CHROME_SOURCE or None,
                      "chrome_note": CHROME_NOTE or None,
                      "webview2": WEBVIEW2 or WEBVIEW2_SYS or (
                          ("system " + WEBVIEW2_VER) if WEBVIEW2_VER else None),
                      "webview2_source": ("bundled" if WEBVIEW2 else
                                          "system" if (WEBVIEW2_VER or WEBVIEW2_SYS) else None),
                      "webview2_version": (bundled_webview2_version() or WEBVIEW2_VER or None),
                      "windows_build": windows_build() or None,
                      "webview2_acl": webview2_acl_state()[0] if WEBVIEW2 else "not-needed",
                      "webview2_acl_note": (WEBVIEW2_ACL_NOTE or
                                            (webview2_acl_state()[1] if WEBVIEW2
                                             else "using system runtime")),
                      "picker": "win32" if os.name == "nt" else "none",
                      "frozen": bool(getattr(sys, "frozen", False)),
                      "build": build_id(),
                      "submit_build": SUBMIT_BUILD,
                      "problems": problems}, ensure_ascii=False, indent=2))
    return 1 if problems else 0


def main():
    code = selftest()                 # 必须在 import webview 之前
    if code is not None:
        raise SystemExit(code)

    # 同样必须在 import webview 之前：缺运行时 pywebview 会抛一句看不懂的异常
    if not require_webview2():
        raise SystemExit(2)

    # Win10 + 随包 Fixed WebView2 要先补 AppContainer 读执行权限，否则 Renderer 起不来。
    # 补不上就退回系统 Evergreen；两者都没有就退出，并把该执行的命令说清楚。
    if not prepare_webview2():
        raise SystemExit(3)

    import webview

    # 包内固定版 WebView2：必须在 create_window 之前设好，否则会用系统那份
    # （或者干脆没有、退回 IE 内核）。没有随包就交给系统。
    if WEBVIEW2:
        os.environ["WEBVIEW2_BROWSER_EXECUTABLE_FOLDER"] = WEBVIEW2

    ensure_library()
    # 同一个库被两个副本同时写会互相覆盖：拿不到独占锁就只让看，不让写
    global LIB_EXCLUSIVE
    if not lock_library():
        ask = ("这个牌谱库正被另一个 Mortal Coach 使用：\n" + str(LIB) + "\n\n"
               "同时写入会互相覆盖恶手记录和图片。\n\n"
               "「是」= 继续浏览（分析、删除会暂时不可用）\n"
               "「否」= 退出，先去关掉另一个窗口")
        if LIB_STATE == "denied":
            ask = ("没法在这个牌谱库里建锁文件（权限不足或只读位置）：\n" + str(LIB) + "\n\n"
                   "确认不了有没有别的窗口在写，所以这次只能看，不能分析/删除。\n\n"
                   "「是」= 只读浏览\n「否」= 退出，换个可写目录再试")
        if _msgbox(ask, APP_TITLE, 0x4 | 0x30 | 0x10000) != 6:
            raise SystemExit(4)
    if "--devtools" in sys.argv or "--shot" in sys.argv:
        os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--remote-debugging-port=9333"
    # 让子进程（pipeline / mk_coach / submit_auto）拿到同一套目录
    os.environ["MC_APP"] = str(APP_ROOT)
    os.environ["MC_LIB"] = str(LIB)
    port = 8777
    for p in (8777, 8778, 8779):
        if not port_open(p):
            port = p
            break
    else:
        port = 8780
    serve(port)
    api = Api()
    api.port = port
    url = start_url(port)
    webview.create_window(
        APP_TITLE,
        url,
        js_api=api,
        width=1760,
        height=980,
        min_size=(1100, 700),
    )
    webview.start(debug="--devtools" in sys.argv,
                  private_mode=False,          # 否则 localStorage 每次启动清空
                  storage_path=webview_storage())


if __name__ == "__main__":
    main()
