# -*- coding: utf-8 -*-
"""统一的路径解析：界面、命令行、两个 BAT、门槛读取都从这里取。

为什么要有这个文件：以前 `rebuild_all.py` 只认 `MC_LIB` 或 `<程序目录>/library`，
在界面里把库改到别处之后，双击「一键重建解读.bat」仍然去重建程序目录下那个库，
两边各写各的，看起来像「重建没生效」。后来界面自己又长出一套解析（会展开 `%VAR%`），
和这里不一致，配了 `%X%/games` 这种路径时两边指向不同目录 —— 所以现在**只保留这一份**。

牌谱库优先级（从高到低）：
  1. 命令行 `--library <目录>`  —— 显式指定，最高优先
  2. 配置文件 `mortal-coach.json` 的 `library`  —— 就是界面上设置的那个
  3. 环境变量 `MC_LIB`  —— 给脚本化调用留的口子；BAT 会先清空外部残留
  4. 默认：`<程序目录>/library`；程序目录不可写时退到按实例分开的用户目录

配置文件的读写位置也在这里定，**读写用同一份判定**：
  · 活动配置 = 程序目录可写那份 `<程序目录>/mortal-coach.json`；程序目录不可写时
    活动配置是实例目录那份 `%LOCALAPPDATA%/mortal-coach/instances/<id>/config.json`；
  · 读：先读活动配置；活动配置还不存在时，才拿另一份当初始种子（迁移旧值）；
  · 写：永远写活动配置。**永远不会去读写 %APPDATA%/mortal-coach/config.json**，
    那是别的副本或旧版本留下的。

解析结果会打印出来（`describe()`），所以双击 BAT 时能直接看到「到底写哪个库」。
"""
import hashlib
import json
import os
import sys
from pathlib import Path

APP = "mortal-coach"


def app_root():
    """程序目录。MC_APP 可覆盖（GUI 启动子进程时会传）。"""
    env = os.environ.get("MC_APP")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent


def instance_key(root=None):
    """按程序目录算稳定短标识：A/B 两份副本各用各的配置与缓存。"""
    raw = str((root or app_root()).resolve()).lower().encode("utf-8", "replace")
    return hashlib.sha1(raw).hexdigest()[:12]


def instance_dir(root=None):
    """本副本专属的用户目录（程序目录不可写时放配置、库与缓存）。"""
    root = root or app_root()
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP / "instances" / instance_key(root)


def can_write(d):
    """真的写一下试试（只读目录、网盘待同步、权限残缺都能测出来）。"""
    try:
        d = Path(d)
        d.mkdir(parents=True, exist_ok=True)
        t = d / ".mc_write_test"
        t.write_text("x", encoding="utf-8")
        t.unlink()
        return True
    except Exception:
        return False


# ---------- 配置文件 ----------

def config_read_paths(root=None, local=None, instance=None):
    """按优先级列出要读的配置文件：**活动配置优先，另一份只当首次种子**。

    「活动配置」与 `config_save_path()` 用同一套判定：程序目录可写就是程序目录那份，
    不可写就是实例目录那份。

    为什么不能固定「先本地后实例」：安装目录只读时（Program Files、只读共享盘），
    目录里那份出厂默认值会永远排在前面，`load_config()` 读到它就 break ——
    用户保存到实例目录的新门槛/新库再也读不回来，界面上表现为「保存成功，重启就丢」。
    实测过：保存 0.42 落盘正确，重读还是 0.10。

    `local` / `instance` 允许调用方覆盖（界面会把这两个路径缓存成模块变量，测试也好替换），
    不传就按程序目录算。
    """
    root = root or app_root()
    local = Path(local) if local else root / "mortal-coach.json"
    inst = Path(instance) if instance else instance_dir(root) / "config.json"
    active = config_save_path(root, local=local, instance=inst)
    seed = inst if active == local else local
    out = [active]
    if seed != active:
        out.append(seed)
    return out


def config_save_path(root=None, local=None, instance=None):
    """该往哪写配置：程序目录可写就写它，否则写实例目录。"""
    root = root or app_root()
    local = Path(local) if local else root / "mortal-coach.json"
    inst = Path(instance) if instance else instance_dir(root) / "config.json"
    if can_write(local.parent):
        return local
    inst.parent.mkdir(parents=True, exist_ok=True)
    return inst


def config_file(root=None, local=None, instance=None):
    """当前**有效**的配置文件：活动配置存在就是它，否则退到种子；都没有返回 None。

    CLI 与界面用的是同一个函数，所以「界面里保存的门槛」和「BAT 重建时用的门槛」
    不会各读一份。
    """
    for p in config_read_paths(root, local=local, instance=instance):
        if p.exists():
            return p
    return None


# ---------- 牌谱库 ----------

def _expand(raw, root):
    """统一展开：环境变量、~、相对路径按程序目录解析、最后取绝对路径。

    这三条以前 GUI 和 CLI 各写一半，`%VAR%/games` 在 CLI 里会被当成字面目录名。
    """
    s = os.path.expandvars(os.path.expanduser(str(raw).strip()))
    p = Path(s)
    if not p.is_absolute():
        p = Path(root) / p
    return p


def default_library(root=None):
    """默认库：程序目录下的 library；程序目录不可写就退到实例目录。"""
    root = root or app_root()
    if can_write(root):
        return root / "library"
    return instance_dir(root) / "library"


def library_value(raw, root=None):
    """把配置里的 library 字段解析成绝对路径（空串 = 默认库）。"""
    root = root or app_root()
    raw = str(raw or "").strip()
    if not raw:
        return default_library(root)
    return _expand(raw, root)


def parse_library_arg(argv):
    """从参数列表里取 --library。支持 `--library X` 与 `--library=X`。"""
    for i, a in enumerate(argv):
        if a == "--library" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--library="):
            return a.split("=", 1)[1]
    return ""


def _config_library(root):
    p = config_file(root)
    if not p:
        return "", None
    try:
        v = (json.loads(p.read_text(encoding="utf-8")) or {}).get("library") or ""
    except Exception:
        return "", p
    return str(v), p


def library(explicit=""):
    """返回牌谱库路径（绝对路径，但不要求已存在）。"""
    root = app_root()
    if explicit:
        return _expand(explicit, root)
    v, _ = _config_library(root)
    if v:
        return library_value(v, root)
    env = (os.environ.get("MC_LIB") or "").strip()
    if env:
        return _expand(env, root)
    return default_library(root)


def library_source(explicit=""):
    """刚才那个库是从哪来的，给人看的。"""
    root = app_root()
    if explicit:
        return "--library 参数"
    v, p = _config_library(root)
    if v:
        return f"配置文件 {p.name}"
    if (os.environ.get("MC_LIB") or "").strip():
        return "环境变量 MC_LIB"
    if not can_write(root):
        return "默认（程序目录只读，改用本副本的用户目录）"
    return "默认（程序目录下 library）"


def describe(explicit=""):
    """BAT / CLI 开头打印的一行：实际库 + 来源。"""
    return f"牌谱库：{library(explicit)}（来源：{library_source(explicit)}）"


def apply(explicit=""):
    """把解析结果写回环境变量，供 subprocess 与 pipeline_one 使用。"""
    root = app_root()
    lib = library(explicit)
    os.environ["MC_APP"] = str(root)
    os.environ["MC_LIB"] = str(lib)
    return root, lib


# ---------- 跨进程库锁 ----------
#
# 语义：同一个牌谱库同一时刻只允许**一个**进程写。读不受限制。
# 三个状态必须分得清，不能用一个 bool 糊过去：
#   ok      —— 拿到了，可以写
#   busy    —— 别人正拿着，绝不能写
#   denied  —— 锁文件建不出来（权限、只读介质、共享盘不支持），既然无法确认
#              有没有别的写入者，也不能写（上一版这里返回 True，等于放行）。
LOCK_OK, LOCK_BUSY, LOCK_DENIED = "ok", "busy", "denied"


def acquire_lock(lib):
    """尝试独占库。返回 `(status, handle)`；只有 `LOCK_OK` 才该写。

    handle 要**一直持有**（进程退出或崩溃时由系统释放，不会留僵尸锁）。
    """
    p = Path(lib) / ".mc-lock"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        f = open(p, "a+b")
    except OSError:
        return LOCK_DENIED, None
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return LOCK_BUSY, None          # 有人拿着
    except Exception:
        f.close()
        return LOCK_DENIED, None        # 这个文件系统不支持加锁
    return LOCK_OK, f


def try_lock(lib):
    """老接口，给只关心「能不能写」的调用方。

    拿到 → 文件对象；被占用 → None；锁不可用 → False。
    注意 False 和 None 都不是「拿到」，用 `if h:` / `if h is True:` 都能判对。
    """
    status, h = acquire_lock(lib)
    if status == LOCK_OK:
        return h
    if status == LOCK_BUSY:
        return None
    return False


def _pid_alive(pid):
    """这个 pid 还活着吗。Windows 不能拿 os.kill(pid, 0) —— 那会 TerminateProcess。"""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except Exception:
            return True
    try:
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # QUERY_LIMITED_INFORMATION
        if not h:
            return False
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    except Exception:
        return False


def stamp_lock_owner(lib):
    """把「本进程持有这个库的锁」写进环境变量，传给子进程。"""
    os.environ["MC_LIB_LOCK_OWNER"] = str(os.getpid())
    os.environ["MC_LIB_LOCK_PATH"] = str(Path(lib).resolve())


def lock_delegated(lib):
    """父进程是否已经持有同一个库的锁（界面的 pipeline / mk_coach 子进程据此免二次加锁）。

    只认**直接父进程**：孙进程由它爹在跑的时候重新盖章（`stamp_lock_owner`），
    所以链路是「每层都指向自己的父进程」。这样环境变量残留、别人手工塞一个
    `MC_LIB_LOCK_OWNER` 都骗不过去。
    """
    owner = (os.environ.get("MC_LIB_LOCK_OWNER") or "").strip()
    path = (os.environ.get("MC_LIB_LOCK_PATH") or "").strip()
    if not owner.isdigit() or not path:
        return False
    try:
        if Path(path).resolve() != Path(lib).resolve():
            return False
    except Exception:
        return False
    if int(owner) != os.getppid():
        return False
    return _pid_alive(int(owner))


def guard_writable(lib, who="这个命令"):
    """写库前的统一闸门：`(ok, handle, msg)`。ok 时 handle 必须一直持有。

    命令行入口（rebuild_all / refresh_text / mk_coach / pipeline_one）都必须过这一关，
    否则「GUI 加了锁」只锁住了 GUI 自己：实测独占锁被持有时跑重建，照样往库里写。
    """
    if lock_delegated(lib):
        stamp_lock_owner(lib)           # 逐层重戳，孙进程认自己的父进程
        return True, None, ""
    status, h = acquire_lock(lib)
    if status == LOCK_OK:
        stamp_lock_owner(lib)
        return True, h, ""
    if status == LOCK_BUSY:
        return False, None, (
            f"{lib}\n正被另一个 Mortal Coach 写入（.mc-lock 被占用），{who}没有写任何文件。\n"
            f"请先关掉那个窗口或进程，再重试。")
    return False, None, (
        f"{lib}\n建不出锁文件 .mc-lock（权限不足或只读介质），{who}没有写任何文件。\n"
        f"无法确认是否有别的进程在写，为安全起见不继续。"
        f"若这个目录确实要临时用，请换到可写目录。")


if __name__ == "__main__":
    print(describe(parse_library_arg(sys.argv[1:])))
