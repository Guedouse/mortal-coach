# -*- coding: utf-8 -*-
"""构建干净便携发行包 —— 发行包只由白名单构造，不直接压开发目录。

为什么单独写这个脚本：手工右键压缩会把 `library/` 里自己的牌谱、截图、日志一起发出去，
`.gitignore` 管不到手工压缩。这里把「哪些文件能进包」写成代码，并且在打包完成后
**重新打开最终的 ZIP** 扫描禁入项，命中就失败——检查最终产物，而不是只检查中间目录。

用法：
    runtime\\python\\python.exe build_release.py
    runtime\\python\\python.exe build_release.py --out D:\\dist
    runtime\\python\\python.exe build_release.py --out D:\\dist --version v1.0
    runtime\\python\\python.exe build_release.py --no-zip      # 只做清单与检查

`--version` 决定最终文件名、manifest 与 SHA256SUMS 里的版本；不传就用「日期-提交」。
**不要手工重命名产出的 ZIP**：改名后校验文件与 manifest 指向的文件名对不上，
别人按清单核验时第一步就会失败。要换名字就带 `--version` 重新打。

产物：
    <out>/mortal-coach-<version>-windows-x64-lite.zip
    <out>/SHA256SUMS.txt
    <out>/release-manifest.json
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
APP_NAME = "mortal-coach"

# 顶层必须随包的文件（不在就报错）
# 两个 BAT 是给普通用户的维护入口；requirements.txt / build_release.py 随包是为了
# 让 README 里那几条命令在解压目录里真的能跑（以前包里没有，照着做全报错）。
REQUIRED_FILES = [
    "mortal-coach.exe",
    "README.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "使用说明.md",
    "CHANGELOG.md",
    "PRIVACY.md",
    "rebuild.bat",
    "一键重建解读.bat",
    "requirements.txt",
    "build_release.py",
]

# 整目录随包
# docs / tests 都要带：包里的 README 指向 docs/4、docs/5，tools/test_shanten.mjs
# 要读 tests/shanten_cases.json，缺了就是死链 / ENOENT。
INCLUDE_DIRS = ["assets", "app", "scripts", "tools", "tests", "docs", "licenses", "runtime"]

# full 版额外带的运行环境。lite 版**明确不带**（验包会反向检查这两个目录不存在），
# 少了两边都不会"悄悄带一半"。
FULL_DIRS = ["runtime/webview2"]

# 两种发行资产：文件名只差最后一段，验包也必须按同一口径检查
FLAVORS = {
    "lite": "不带浏览器与 WebView2，用系统那份；包小、启动快",
    "full": "自带界面所需 WebView2；提交牌谱使用用户安装的 Chrome/Edge 和独立应用资料目录",
}

# 任何位置都不进包
SKIP_DIRS = {
    ".git", "build", "release", "dist", "__pycache__", ".idea", ".vscode",
    "library/work", "library/chrome-profile", "library/chrome-profile.old",
}
SKIP_NAMES = {".gitignore", ".gitattributes", "Thumbs.db", "desktop.ini", ".mc-lock"}
SKIP_EXT = {".pyc", ".pyo", ".zip", ".tmp", ".log", ".bak"}

# 发行版的空库：只放这两个空数组，让首页与恶手数为 0；其余目录首次启动自动建
EMPTY_LIBRARY = {
    "library/coach/index.json": b"[]\n",
    "library/bad_moves.json": b"[]\n",
}

# 发行版配置**由这里生成**，不复制开发目录那份（否则哪天开发机把库设到 E 盘，
# 打出来的包就带着别人的路径）。字段与 app/main.py 的 DEFAULT_CONFIG 一致。
EMPTY_CONFIG = {
    "library": "",
    "chrome": "",
    "python": "",
    "node": "",
    "bad": {"thresh": 0.10, "gap": {"severe": 0.50},
            "loss": {"severe": 0.70, "medium": 0.30}},
    "ui": {},
}

# 声明里点名的许可原文，少一份就是声明不实（THIRD_PARTY_NOTICES.md 第 1 节）
REQUIRED_LICENSES = [
    "python-PSF.txt",
    "pillow-LICENSE.txt",
    "node-MIT.txt",
    "i18next-MIT.txt",
    "killer_mortal_gui-MIT.txt",
    "pywebview-BSD-3-Clause.txt",
    "pythonnet-MIT.txt",
    "pyinstaller-bootloader-GPL2-with-exception.txt",
    "riichi-mahjong-tiles-CC0.txt",
    "noto-sans-sc-OFL.txt",
]

# 只有 full 版随包分发的东西，许可原文单列：lite 版里没有它们，也就不该要求
FULL_LICENSES = [
    "webview2-runtime-Microsoft.txt",
]

# 禁入项（最终 ZIP 里出现任意一条就失败）
FORBIDDEN_PATTERNS = [
    (r"(^|/)(Cookies(?:-journal)?|History(?:-journal)?|Login Data|Web Data|Local State|DevToolsActivePort)$", "浏览器个人数据"),
    (r"^runtime/chromium/", "已停止分发的提交浏览器"),
    (r"^library/report/", "个人牌谱报告"),
    (r"^library/img_layout/", "分析图片"),
    (r"^library/logs/", "提交日志"),
    (r"^library/work/", "中间文件"),
    (r"^library/chrome-profile", "浏览器 profile"),
    (r"^library/coach/(?!index\.json$).+\.json$", "单局解读/状态"),
    (r"\.mc-machine$", "机器标识"),
    (r"\.mc-lock$", "库占用锁"),
    (r"(^|/)\.tmp$", "临时文件"),
]

# 泄漏扫描：文本文件里不许出现作者本机路径。
# 只禁「个人目录」，系统自带路径（Windows、Program Files）是正常引用，放行。
#   1) 开发目录 / 任意用户的 home —— 盘符后跟 maa 或 Users\<某人>
#   2) 盘符后直接跟中文目录名 —— 中文用户最容易漏掉的一种
# 判据：盘符前后都要成立（前面不是字母/数字，避免把 https:// 里的 s: 当成盘符），
#      分隔符是单个反斜杠或单个正斜杠（`//` 属于 URL）。
# 注意：截图里的路径文字拦不住（二进制），图要人工看一眼。
LEAK_RES = [
    (re.compile(r"(?<![A-Za-z0-9+.\-])[A-Za-z]:(?:\\|/(?!/))"
                r"(?:maa|Users[\\/]+[^\\/\s\"'<>|]+)", re.I), "本机用户目录"),
    (re.compile(r"(?<![A-Za-z0-9+.\-])[A-Za-z]:(?:\\|/(?!/))"
                r"[^\x00-\x7F][^\\/\r\n\"'<>|]*"), "非 ASCII 目录名"),
]
TEXT_EXT = {".py", ".js", ".mjs", ".json", ".md", ".html", ".css", ".bat", ".txt", ".spec", ".ini", ".cfg"}


def sh(*cmd):
    try:
        r = subprocess.run(cmd, cwd=str(BASE), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20)
        return (r.stdout or "").strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def source_info():
    """无 Git 提交时明确标为 unknown，不把失败命令回显的 HEAD 写成提交号。"""
    commit = sh("git", "rev-parse", "--verify", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        return {"commit": None, "dirty": None}
    return {"commit": commit, "dirty": bool(sh("git", "status", "--porcelain"))}


def version(explicit=""):
    """版本 = 显式传入 > 日期 + 提交前缀。没有 git 就只用日期。

    `--version` 是给「想用 v1.0 这种人类可读版本号」准备的：文件名、manifest、
    SHA256SUMS 三处都由它算出来，改名字必须走这里，不能手工重命名 ZIP ——
    否则校验文件里写的是旧名字，自动化核验第一步就找不到文件。
    """
    if str(explicit or "").strip():
        return str(explicit).strip()
    day = time.strftime("%Y%m%d")
    commit = source_info()["commit"]
    rev = commit[:7] if commit else ""
    return f"{day}-{rev}" if rev else day


def in_skip_dir(rel):
    # 包内解释器只运行分析脚本，不需要开发机后来安装的包管理器。
    if re.match(r"^runtime/python/Lib/site-packages/pip(?:/|-[^/]+\.dist-info(?:/|$)|$)", rel, re.I):
        return True
    return any(rel == d or rel.startswith(d + "/") for d in SKIP_DIRS)


def iter_release_files(flavor="lite"):
    """白名单枚举：返回 (源文件, ZIP 内路径)。这是 staging 的唯一来源。

    `flavor="lite"` 时把 `runtime/chromium`、`runtime/webview2` 整棵子树排除掉：
    开发机上为了打 full 版，这两个目录是真实存在的（1.5 GB 上下），
    不排除就会把 lite 包也撑成 600 MB。
    """
    for name in REQUIRED_FILES:
        p = BASE / name
        if p.exists():
            yield p, name
    for d in INCLUDE_DIRS:
        root = BASE / d
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = Path(dirpath).relative_to(BASE).as_posix()
            dirnames[:] = [x for x in dirnames
                           if not in_skip_dir(f"{rel_dir}/{x}") and x != "__pycache__"
                           and f"{rel_dir}/{x}" != "runtime/chromium"]
            if flavor != "full":
                dirnames[:] = [x for x in dirnames
                               if f"{rel_dir}/{x}" not in FULL_DIRS]
            for f in filenames:
                if f in SKIP_NAMES or Path(f).suffix.lower() in SKIP_EXT:
                    continue
                p = Path(dirpath) / f
                yield p, f"{rel_dir}/{f}"


def find_chrome_exe():
    """开发目录里的随包 Chromium（full 版才有），按 main.bundled_chrome 的顺序找。"""
    base = BASE / "runtime" / "chromium"
    cands = [base / "chrome.exe", base / "chrome-win64" / "chrome.exe",
             base / "chrome-win" / "chrome.exe"]
    try:
        cands += [d / "chrome.exe" for d in sorted(base.iterdir(), reverse=True)]
    except Exception:
        pass
    for c in cands:
        try:
            if c.exists():
                return c
        except Exception:
            continue
    return None


def find_webview2_dir():
    """开发目录里的 WebView2 固定版目录（full 版才有）。"""
    base = BASE / "runtime" / "webview2"
    if not base.exists():
        return None
    if (base / "msedgewebview2.exe").exists():
        return base
    try:
        for d in sorted(base.iterdir(), reverse=True):
            if d.is_dir() and (d / "msedgewebview2.exe").exists():
                return d
    except Exception:
        pass
    return None


def file_version(p):
    """读 exe 的文件版本号（Chromium 不带版本文件，属性里才有）。

    读不到就返回空串 —— 清单里写 `bundled unknown` 也比编一个版本号强。
    """
    if os.name != "nt" or not p:
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        size = ctypes.windll.version.GetFileVersionInfoSizeW(str(p), None)
        if not size:
            return ""
        buf = ctypes.create_string_buffer(size)
        if not ctypes.windll.version.GetFileVersionInfoW(str(p), 0, size, buf):
            return ""
        r = ctypes.c_void_p()
        ln = wintypes.UINT()
        if not ctypes.windll.version.VerQueryValueW(buf, "\\", ctypes.byref(r),
                                                    ctypes.byref(ln)):
            return ""
        # VS_FIXEDFILEINFO：前 8 字节是签名，后面 4 个 DWORD 是 ms/ls 各两段
        val = ctypes.cast(r, ctypes.POINTER(wintypes.DWORD * 4)).contents
        ms, ls = val[2], val[3]
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception:
        return ""


def bat_bytes(p):
    """BAT 在 ZIP 里的字节：**UTF-8 无 BOM + CRLF**。

    为什么不能直接 z.write 源文件：cmd.exe 按行解析批处理，纯 LF 的文件在 Windows 上
    会被截断成半行，报 `'t' 不是内部或外部命令` / `&& was unexpected at this time`。
    仓库里的 `.gitattributes` 虽然写了 `*.bat text eol=crlf`，但那要靠 checkout 才生效，
    打包时不能赌开发机上这份文件的行尾 —— 所以在这里按目标平台规范化。
    BOM 同样要去掉：`@echo off` 前面多三个字节会让 cmd 连第一条命令都认不出来。
    """
    raw = p.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


def check_required(out_dir, flavor="lite"):
    missing = [n for n in REQUIRED_FILES if not (BASE / n).exists()]
    if not (BASE / "licenses").exists():
        missing.append("licenses/（第三方许可原文）")
    need_lic = list(REQUIRED_LICENSES) + (FULL_LICENSES if flavor == "full" else [])
    for name in need_lic:
        if not (BASE / "licenses" / name).exists():
            missing.append(f"licenses/{name}")
    if not (BASE / "runtime" / "python" / "python.exe").exists():
        missing.append("runtime/python/python.exe")
    if not (BASE / "runtime" / "node" / "node.exe").exists():
        missing.append("runtime/node/node.exe")
    if flavor == "full":
        # full 只附界面运行时；日常浏览器由用户安装。
        wv = find_webview2_dir()
        if wv is None:
            missing.append("runtime/webview2/**/msedgewebview2.exe（full 版随包的 WebView2 固定版）")
        elif not (wv / "msedge.dll").exists():
            missing.append(f"{wv.relative_to(BASE).as_posix()}/msedge.dll（固定版解压不完整）")
    if not (BASE / "tests" / "shanten_cases.json").exists():
        missing.append("tests/shanten_cases.json（tools/test_shanten.mjs 要读它）")
    if not (BASE / "assets" / "fonts" / "NotoSansSC-Regular.otf").exists():
        missing.append("assets/fonts/NotoSansSC-Regular.otf（排版图的中文字体，缺了会退到系统字体）")
    if missing:
        print("!! 缺必须随包的文件：")
        for m in missing:
            print("   -", m)
        raise SystemExit(2)


def runtime_versions(flavor="lite"):
    out = {}
    py = BASE / "runtime" / "python" / "python.exe"
    if py.exists():
        out["python"] = sh(str(py), "-c",
                           "import sys,platform;print(sys.version.split()[0], platform.architecture()[0])")
    node = BASE / "runtime" / "node" / "node.exe"
    if node.exists():
        out["node"] = sh(str(node), "-v")
    if flavor == "full":
        wv = find_webview2_dir()
        bundled = ""
        if wv is not None:
            bundled = wv.name if wv.name[:1].isdigit() else "flat"
        out["webview2"] = ("bundled " + bundled) if bundled else "缺失（full 版必须随包）"
    else:
        out["webview2"] = "system（未随包分发）"
    out["chromium"] = "system browser（所有发行版本均不附浏览器）"
    fnt = BASE / "assets" / "fonts" / "NotoSansSC-Regular.otf"
    out["font"] = f"NotoSansSC-Regular {fnt.stat().st_size} bytes" if fnt.exists() else "缺失"
    # 实际钉住的运行依赖也记进来：出了「某台机器上就是不一样」的问题时，
    # 清单里能直接看到这一包是按哪几个版本打的，不用回头问开发机。
    pins = []
    req = BASE / "requirements.txt"
    if req.exists():
        for line in req.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                pins.append(line)
    out["requirements"] = ", ".join(pins) if pins else "未提供 requirements.txt"
    return out


def build(out_dir, make_zip=True, ver="", flavor="lite"):
    check_required(out_dir, flavor)
    ver = version(ver)
    zip_name = f"{APP_NAME}-{ver}-windows-x64-{flavor}.zip"
    zip_path = out_dir / zip_name
    out_dir.mkdir(parents=True, exist_ok=True)

    files = list(iter_release_files(flavor))
    print(f"白名单（{flavor}）：{len(files)} 个文件 → {zip_name}")

    if not make_zip:
        for p, arc in files[:5]:
            print("  ", arc)
        print("   ...")
        return None

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p, arc in files:
            if arc.lower().endswith(".bat") and "/" not in arc:
                z.writestr(arc, bat_bytes(p))
            else:
                z.write(p, arc)
        for arc, data in EMPTY_LIBRARY.items():
            z.writestr(arc, data)
        # 配置由模板生成：不复制开发目录那份
        z.writestr("mortal-coach.json",
                   json.dumps(EMPTY_CONFIG, ensure_ascii=False, indent=2) + "\n")
        # manifest 先写占位，压缩后回填 zip 的 sha256
        manifest = {
            "name": APP_NAME,
            "version": ver,
            "flavor": flavor,
            **source_info(),
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "platform": "windows-x64",
            "runtimes": runtime_versions(flavor),
            "files": len(files) + len(EMPTY_LIBRARY) + 2,
            "zip": zip_name,
            "note": "library/ 为空库：只含 coach/index.json=[] 与 bad_moves.json=[]；"
                    "mortal-coach.json 由 build_release.EMPTY_CONFIG 生成；"
                    + ("full 版仅附 runtime/webview2 界面运行时，提交使用系统浏览器的独立应用资料目录"
                       if flavor == "full" else
                       "lite 版使用系统 WebView2，提交使用系统浏览器的独立应用资料目录"),
        }
        z.writestr("release-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    size = zip_path.stat().st_size
    sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    manifest["zip_bytes"] = size
    manifest["zip_sha256"] = sha
    (out_dir / "release-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    # 两种资产各存一份明细：先打 lite 再打 full 时，release-manifest.json 会被后者覆盖，
    # 只有 per-flavor 这份能同时保留两个包的构建信息。
    (out_dir / f"release-manifest-{flavor}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    # SHA256SUMS 也合并写：同一目录里同时发布 lite 与 full，两份哈希都得在，
    # 否则后打的那个会把先打的覆盖掉，用户按清单核验第一个包时找不到对应行。
    sums = {}
    sums_path = out_dir / "SHA256SUMS.txt"
    if sums_path.exists():
        for line in sums_path.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split("  ", 1)
            if len(parts) == 2 and parts[1].strip():
                sums[parts[1].strip()] = parts[0].strip()
    sums[zip_name] = sha
    sums_path.write_text("".join(f"{v}  {k}\n" for k, v in sorted(sums.items())),
                         encoding="utf-8")
    print(f"已生成：{zip_path}  {size / 1048576:.1f} MB")
    print(f"SHA256：{sha}")
    return zip_path


def verify(zip_path, flavor="lite"):
    """重新打开最终 ZIP 做禁入、泄漏、配置与许可清单检查。检查产物，不检查中间目录。"""
    problems = []
    checked = []
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()

        for pat, why in FORBIDDEN_PATTERNS:
            hit = [n for n in names if re.search(pat, n)]
            if hit:
                problems.append(f"含{why}：{len(hit)} 项，例如 {hit[:3]}")

        # 必带文件逐个点名：缺一个就失败，不能"目录里有点东西"就算过
        musts = ("LICENSE", "THIRD_PARTY_NOTICES.md", "README.md", "使用说明.md",
                 "mortal-coach.exe", "mortal-coach.json",
                 "rebuild.bat", "一键重建解读.bat", "requirements.txt", "build_release.py",
                 "runtime/python/python.exe", "runtime/node/node.exe",
                 "assets/fonts/NotoSansSC-Regular.otf",
                 "tests/shanten_cases.json", "tests/test_urls.py", "tools/test_shanten.mjs",
                 "library/coach/index.json", "library/bad_moves.json")
        for must in musts:
            if must not in names:
                problems.append(f"缺少 {must}")
        for name in REQUIRED_LICENSES + (FULL_LICENSES if flavor == "full" else []):
            if f"licenses/{name}" not in names:
                problems.append(f"缺少许可原文 licenses/{name}")
        checked.append(f"必带文件 {len(musts)} 项 + 许可 "
                       f"{len(REQUIRED_LICENSES) + (len(FULL_LICENSES) if flavor == 'full' else 0)} 份")

        # 两种资产的差别就在这里：lite 不许夹带，full 必须真有、而且解压得完整。
        # 只看"目录存在"是不够的 —— 断点续传失败、只解了一层，都会留下一个空壳目录。
        if flavor == "full":
            wv = [n for n in names if re.match(r"^runtime/webview2/([^/]+/)?msedgewebview2\.exe$", n)]
            wv_all = [n for n in names if n.startswith("runtime/webview2/")]
            for m in ("msedge.dll", "resources.pak", "icudtl.dat"):
                if not any(n.startswith("runtime/webview2/") and n.endswith("/" + m) for n in wv_all):
                    problems.append(f"full 版缺少随包 WebView2 文件 {m}")
            if not wv:
                problems.append("full 版缺 runtime/webview2/**/msedgewebview2.exe")
            if len(wv_all) < 400:
                problems.append(f"随包 WebView2 只有 {len(wv_all)} 个文件（官方固定版是 548 个），"
                                "像是没解压完整")
            checked.append(f"随包 WebView2 {len(wv_all)} 项；不包含提交浏览器")
        else:
            stray = [n for n in names
                     if n.startswith("runtime/chromium/") or n.startswith("runtime/webview2/")]
            if stray:
                problems.append(f"lite 版不该带随包浏览器/WebView2，实际有 {len(stray)} 项"
                                f"（例如 {stray[:2]}）")
            checked.append("lite 版确认不含随包浏览器与 WebView2")

        # BAT 的字节格式必须当场验：Windows 只认 CRLF，BOM 会让第一条命令就失败。
        # 这不是"文件在不在"的问题，是"能不能跑"的问题，所以要读 ZIP 里的实际字节。
        # 只查我们自己的启动脚本：runtime/python 里带的是 CPython 标准库的 .bat，
        # 那是第三方原样文件，不该被我们改写（也不该拿它的行尾判我们的合规）。
        bats = [n for n in names if n.lower().endswith(".bat") and "/" not in n]
        for n in bats:
            raw = z.read(n)
            if raw.startswith(b"\xef\xbb\xbf"):
                problems.append(f"{n} 带 UTF-8 BOM，cmd.exe 会认不出第一条命令")
            lone = raw.replace(b"\r\n", b"").count(b"\n")
            if lone:
                problems.append(f"{n} 有 {lone} 处裸 LF（会截断命令），必须是 CRLF")
        if not bats:
            problems.append("包里没有 .bat")
        checked.append(f"BAT {len(bats)} 份为 CRLF、无 BOM")

        # 发行配置必须干净：不能带着开发机的库/浏览器路径
        try:
            mc = json.loads(z.read("mortal-coach.json").decode("utf-8"))
        except Exception as e:
            problems.append(f"mortal-coach.json 读不出来：{e}")
        else:
            for k in ("library", "chrome", "python", "node"):
                if str(mc.get(k) or "").strip():
                    problems.append(f"发行配置 {k} 不是空值：{mc.get(k)!r}")
            if (mc.get("ui") or {}).get("welcome_done"):
                problems.append("发行配置 ui.welcome_done 应为假（否则新用户看不到教程）")
            bad = mc.get("bad") or {}
            if not isinstance(bad.get("thresh"), (int, float)):
                problems.append("发行配置缺 bad.thresh")
            checked.append("发行配置四个路径为空、教程未读")

        # 本机路径泄漏
        for n in names:
            if Path(n).suffix.lower() in TEXT_EXT:
                try:
                    txt = z.read(n).decode("utf-8", "ignore")
                except Exception:
                    continue
                for rx, why in LEAK_RES:
                    for m in rx.finditer(txt):
                        problems.append(f"{n} 里有{why}：{m.group(0)}")
                        break
        checked.append(f"文本文件 {sum(1 for n in names if Path(n).suffix.lower() in TEXT_EXT)} 个无本机路径")

        idx = json.loads(z.read("library/coach/index.json").decode("utf-8"))
        bad = json.loads(z.read("library/bad_moves.json").decode("utf-8"))
        if idx != [] or bad != []:
            problems.append("发行库不是空库")
        checked.append("空库（index/bad_moves 都是 []）")

        # 元数据自洽：ZIP 里有 release-manifest.json，它写的 zip 名必须就是当前文件名。
        # 手工改名 / 复用旧 manifest 都会在这里露出来，而不是等到别人按清单核验时才发现。
        try:
            man = json.loads(z.read("release-manifest.json").decode("utf-8"))
        except Exception as e:
            problems.append(f"release-manifest.json 读不出来：{e}")
        else:
            if man.get("zip") != zip_path.name:
                problems.append(f"manifest 里的 zip 是 {man.get('zip')!r}，"
                                f"实际文件名是 {zip_path.name!r}（改名必须走 --version 重新打包）")
            if man.get("flavor") != flavor:
                problems.append(f"manifest 里的 flavor 是 {man.get('flavor')!r}，"
                                f"实际打的是 {flavor!r}")
            checked.append("manifest 的 zip / flavor 字段与实际产物一致")

    print(f"\n验包：{zip_path.name} · {len(names)} 项")
    if problems:
        print("!! 验包失败：")
        for p in problems:
            print("   -", p)
        return False
    print("验包通过，本次实际检查了：")
    for c in checked:
        print("   ·", c)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(BASE.parent), help="输出目录（默认与程序目录同级）")
    ap.add_argument("--no-zip", action="store_true", help="只列白名单，不打包")
    ap.add_argument("--version", default="",
                    help="发布版本号（默认 日期-提交）；文件名、manifest、SHA256SUMS 都由它生成")
    ap.add_argument("--flavor", choices=sorted(FLAVORS), default="lite",
                    help="；".join(f"{k} = {v}" for k, v in FLAVORS.items()))
    args = ap.parse_args()
    out_dir = Path(args.out)
    zp = build(out_dir, make_zip=not args.no_zip, ver=args.version, flavor=args.flavor)
    if zp and not verify(zp, args.flavor):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
