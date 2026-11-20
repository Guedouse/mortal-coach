# -*- coding: utf-8 -*-
"""一条命令：一份 Mortal 报告 → 逐手中文解读 + 牌型对照图 + 回放器查表数据。

用法：
    python scripts/pipeline_one.py <报告.json> <标签> [--no-img] [--quiet]

例如：
    python scripts/pipeline_one.py assets/kd/report/261118.json 261118

做的事（全部本机计算，不联网、不调用任何大模型）：
  ① extract_core.extract   按 player_id 定座位，从 mjai_log + review 里挑出恶手
  ② explain.gen            为每一手写「Mortal 为什么这么打」的中文解读（模板＋牌理计算）
  ③ build_positions        算出 killerducky 牌桌坐标 (hand, ply)，前端据此查表
  ④ mk_layout.build        画 600×334 的「两种切法对照图」（没有 Pillow 就跳过）
  ⑤ 合并进 data/bad_moves.json，再调 mk_coach 生成 assets/kd/coach/<标签>.json

状态：无论成败都写 assets/kd/coach/<标签>.status.json（见 docs/3 §2 P0-3），
      退出码 0 = 完全成功（含「本局没有恶手」这种合法空结果），1 = 失败或部分失败。
"""
import json
import os
import subprocess
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

BASE = Path(os.environ.get("MC_APP") or Path(__file__).resolve().parent.parent)
LIB = Path(os.environ.get("MC_LIB") or BASE / "library")
sys.path.insert(0, str(BASE / "scripts"))

import badcfg as BC                      # noqa: E402
import explain as X                      # noqa: E402
import extract_core as EC                # noqa: E402
import paths as PATHS                    # noqa: E402

DATA = LIB
WORK = DATA / "work"
LAYOUT = LIB / "img_layout"
COACH_DIR = LIB / "coach"
# 库锁句柄：拿到后一直持有，进程结束由系统释放
_LOCK = None
PIPELINE_VERSION = "8"      # 8 = 门槛移进设置（bad.thresh，默认 10pt）+ 只留严重 / 中等两档
                            # 7 = 入库门槛 30pt→10pt
                            # 6 = 已听牌不再写「做牌方向」+ 对对和不再误判为主线 + 场况措辞
                            # 5 = 正文牌名改牌图占位 + 打点判据（含混一色/七对子等通用番数对比）
                            # 4 = 牌效页去掉文字牌名罗列，进张交由牌图展示；攻防页见 v3


class StepError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code
        self.msg = msg


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _has_pil():
    try:
        import PIL  # noqa: F401
        return True
    except Exception:
        return False


def merge_into_library(recs, tag):
    """把该局记录并入 data/bad_moves.json（同局旧记录整体替换）。"""
    p = DATA / "bad_moves.json"
    old = []
    if p.exists():
        try:
            old = json.load(open(p, encoding="utf-8"))
        except Exception:
            old = []
    kept = [r for r in old if r.get("game") != tag]
    allrec = kept + recs
    json.dump(allrec, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return len(kept), len(allrec)


def write_status(tag, st):
    COACH_DIR.mkdir(parents=True, exist_ok=True)
    p = COACH_DIR / f"{tag}.status.json"
    tmp = COACH_DIR / f".{tag}.status.tmp"
    try:
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(p)
    except Exception as e:
        print(f"  !! 状态文件写入失败：{e}")


def _lib_rel(p):
    """报告路径 → 相对牌谱库的写法（不在库里就退回文件名）。

    状态文件跟着发行包走，写绝对路径等于把本机的盘符 / 用户名一起发出去；
    库整包搬到别的目录后，绝对路径也会立刻失效。
    """
    try:
        return Path(p).resolve().relative_to(LIB.resolve()).as_posix()
    except Exception:
        return Path(p).name


def run(report_path, tag, img=True, quiet=False):
    """跑一局。返回状态 dict；任何失败都写进状态文件，不抛给调用方。"""
    t0 = time.time()
    log = print if not quiet else (lambda *a, **k: None)
    report_path = Path(report_path)
    st = {
        "tag": tag,
        "report_path": str(report_path),
        "pipeline_version": PIPELINE_VERSION,
        "bad_thresh": BC.entry_thresh(),   # 这局是按哪个门槛提的；改门槛后需要重建
        "started_at": _now(),
        "finished_at": None,
        "elapsed": 0,
        "report_valid": False,
        "events": 0,
        "reviewed": 0,
        "entries": 0,
        "matched": 0,
        "threshold_filtered": 0,
        "explain_ok": 0,
        "explain_failed": 0,
        "position_ok": 0,
        "position_missing": 0,
        "coach_moves": 0,
        "seat": None,
        "seat_source": "",
        "stage": "START",
        "status": "failed",
        "ok": False,
        "error_code": None,
        "error_message": None,
        "no_bad_moves": False,
        "warnings": [],
        "explain_errors": [],
    }

    try:
        st["stage"] = "LOADING"
        if not report_path.exists():
            raise StepError("REPORT_MISSING", f"报告不存在：{report_path}")
        try:
            data = json.load(open(report_path, encoding="utf-8"))
        except Exception as e:
            raise StepError("REPORT_SCHEMA_INVALID", f"报告不是合法 JSON：{e}")

        mjai_log = data.get("mjai_log") or (data.get("review") or {}).get("mjai_log") or []
        rev = data.get("review") or {}
        if not isinstance(mjai_log, list) or not mjai_log:
            raise StepError("REPORT_SCHEMA_INVALID", "报告里没有 mjai_log，无法重建场况")
        if not isinstance(rev.get("kyokus"), list) or not rev.get("kyokus"):
            raise StepError("EXTRACT_FAILED", "review.kyokus 为空，Mortal 没有给出评分")
        st["report_valid"] = True
        st["events"] = len(mjai_log)
        st["reviewed"] = rev.get("total_reviewed")

        # 座位：优先 report.player_id，其次 review.player_id，最后按 entries 里 actor 最多猜
        seat = data.get("player_id")
        if isinstance(seat, int) and 0 <= seat <= 3:
            st["seat_source"] = "report.player_id"
        else:
            seat = rev.get("player_id") if isinstance(rev.get("player_id"), int) else None
            if seat is not None and 0 <= seat <= 3:
                st["seat_source"] = "review.player_id"
            else:
                c = Counter()
                for k in rev.get("kyokus") or []:
                    for e in k.get("entries") or []:
                        a = e.get("actual") or {}
                        if isinstance(a.get("actor"), int):
                            c[a["actor"]] += 1
                seat = c.most_common(1)[0][0] if c else 0
                st["seat_source"] = "inferred_from_entries"
                st["warnings"].append("报告里没有 player_id，座位按评分条目里出现最多的 actor 推断")
        st["seat"] = seat
        log(f"[1/5] 座位 {seat}（{['东','南','西','北'][seat]}家，{st['seat_source']}） · "
            f"事件 {len(mjai_log)} · 评过 {rev.get('total_reviewed')} 手 · rating {rev.get('rating')}")

        # ① 恶手
        st["stage"] = "EXTRACTING"
        stats = {}
        try:
            recs = EC.extract(mjai_log, rev, seat, game=tag,
                              thresh=BC.entry_thresh(), stats=stats)
        except Exception as e:
            traceback.print_exc()
            raise StepError("EXTRACT_FAILED", f"恶手提取失败：{type(e).__name__}: {e}")
        st.update({k: stats.get(k, 0) for k in
                   ("entries", "matched", "threshold_filtered")})
        log(f"[2/5] 恶手 {len(recs)} 手 / 评分条目 {stats.get('entries')}"
            f"（对齐 {stats.get('matched')} · 阈值筛掉 {stats.get('threshold_filtered')}）"
            f"  分类 {dict(Counter(r['cls'] for r in recs))}")
        if not recs:
            st["no_bad_moves"] = True
            log(f"      这一局没有达到门槛（{BC.entry_thresh() * 100:.0f}pt）的恶手"
                " —— 属正常结果，不是失败")
        elif stats.get("matched", 0) == 0:
            st["warnings"].append("评分条目一条都没对上牌谱事件，可能是 Mortal 报告格式变了")

        # ② 解读（逐条隔离：一手失败不影响其他手）
        st["stage"] = "EXPLAINING"
        for n, r in enumerate(recs, 1):
            try:
                t, sev, txt = X.gen(r)
                r["tag"], r["severity"], r["explain"] = t, sev, txt
                if not (txt or "").strip():
                    st["explain_errors"].append({"i": r.get("i"), "err": "解读为空"})
                    st["explain_failed"] += 1
                else:
                    st["explain_ok"] += 1
            except Exception as e:
                st["explain_errors"].append({"i": r.get("i"), "err": f"{type(e).__name__}: {e}"})
                st["explain_failed"] += 1
                r["severity"] = r.get("severity") or ""
                r["explain"] = r.get("explain") or ""
            if n % 10 == 0 or n == len(recs):
                log(f"[3/5] 解读 {n}/{len(recs)}（失败 {st['explain_failed']}）")

        # ③ 坐标
        st["stage"] = "POSITIONING"
        pos = EC.build_positions(mjai_log)
        for r in recs:
            p = pos.get(r["i"])
            r["kd_hand"], r["kd_ply"] = p if p else (None, None)
            if p is None:
                st["position_missing"] += 1
            else:
                st["position_ok"] += 1
        log(f"[4/5] 牌桌坐标已定位 {st['position_ok']}/{len(recs)}")

        # ④ 牌型对照图（没有 Pillow 就跳过，不影响解读）
        st["stage"] = "LAYOUT"
        if img and recs:
            if not _has_pil():
                st["warnings"].append("当前解释器没有 Pillow，已跳过 PNG 对照图（页面内手牌图不受影响）")
                log("[5/5] 跳过制图（当前解释器没有 Pillow）")
            else:
                import mk_layout as L
                LAYOUT.mkdir(parents=True, exist_ok=True)
                grp = Counter((r["game"], r["i"]) for r in recs)
                ordn = {}
                for n, r in enumerate(recs, 1):
                    base = f"{r['game']}_{r['i']:04d}"
                    if grp[(r["game"], r["i"])] > 1:
                        ordn[base] = ordn.get(base, 0) + 1
                        name = f"{base}_{ordn[base]}.png"
                    else:
                        name = f"{base}.png"
                    p = LAYOUT / name
                    try:
                        L.build(r, p)
                        r["img_layout"] = str(p)
                    except Exception as e:
                        st["warnings"].append(f"第 {r.get('i')} 手对照图失败：{type(e).__name__}: {e}")
                    if n % 10 == 0 or n == len(recs):
                        log(f"[5/5] 制图 {n}/{len(recs)}")

        # ⑤ 落盘 + coach 查表
        st["stage"] = "COACH_EXPORTING"
        # 报告必须在 assets/kd/report/ 下：mk_coach 与侧栏局列表都以这个目录为准
        want = LIB / "report" / f"{tag}.json"
        if report_path.resolve() != want.resolve():
            want.parent.mkdir(parents=True, exist_ok=True)
            want.write_bytes(report_path.read_bytes())
            log(f"      报告已归位到 {want}")
            report_path = want
        WORK.mkdir(parents=True, exist_ok=True)
        json.dump(recs, open(WORK / f"{tag}.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        kept, total = merge_into_library(recs, tag)
        log(f"      写入 work/{tag}.json；库内共 {total} 手（本局 {len(recs)} 手）")

        r = subprocess.run([sys.executable, str(BASE / "scripts" / "mk_coach.py")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise StepError("COACH_EXPORT_FAILED",
                            "mk_coach 失败：" + ((r.stdout or "") + (r.stderr or "")).strip()[-400:])
        cp = COACH_DIR / f"{tag}.json"
        if not cp.exists():
            raise StepError("COACH_EXPORT_FAILED", "mk_coach 跑完了但没有生成 coach 文件")
        try:
            st["coach_moves"] = len((json.load(open(cp, encoding="utf-8")).get("moves") or {}))
        except Exception as e:
            raise StepError("COACH_EXPORT_FAILED", f"coach 文件读不出来：{e}")
        log(f"      coach 数据已更新：{st['coach_moves']} 手可查")

        st["stage"] = "READY"
        if st["explain_failed"]:
            st["status"] = "partial"
            st["ok"] = False
            st["error_code"] = "PARTIAL"
            st["error_message"] = f"{st['explain_failed']} 手解读生成失败"
        else:
            st["status"] = "ok"
            st["ok"] = True

    except StepError as e:
        st.update(stage="FAILED", status="failed", ok=False,
                  error_code=e.code, error_message=e.msg)
        log(f"  !! 失败 [{e.code}] {e.msg}")
    except Exception as e:
        traceback.print_exc()
        st.update(stage="FAILED", status="failed", ok=False,
                  error_code="UNEXPECTED", error_message=f"{type(e).__name__}: {e}")
        log(f"  !! 未预期错误 {type(e).__name__}: {e}")

    st["finished_at"] = _now()
    st["elapsed"] = round(time.time() - t0, 1)
    st["report_path"] = _lib_rel(report_path)     # 只留相对路径，别把本机盘符写进发行包
    write_status(tag, st)
    return st


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        raise SystemExit(1)
    report_path, tag = args[0], args[1]
    # 单独跑也要过锁闸；被界面 / rebuild_all 派下来时走的是「父进程已持锁」的授权路径，
    # 不会跟自己人抢锁（否则界面一分析就把自己锁死）。
    ok, handle, msg = PATHS.guard_writable(LIB, "这一局的分析")
    if not ok:
        print(msg, file=sys.stderr)
        raise SystemExit(3)
    globals()["_LOCK"] = handle
    st = run(report_path, tag,
             img="--no-img" not in sys.argv,
             quiet="--quiet" in sys.argv)
    if st.get("status") == "ok":
        raise SystemExit(0)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
