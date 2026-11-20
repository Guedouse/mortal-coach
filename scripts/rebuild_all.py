# -*- coding: utf-8 -*-
"""补齐所有缺解读 / 状态不一致的局（或 --force 全量重建）。

用法：
    python scripts/rebuild_all.py            # 只处理缺的、坏掉的、过期版本的局
    python scripts/rebuild_all.py --force    # 全部重算（约 16~33 秒/局）
    python scripts/rebuild_all.py --no-img   # 只出文字，不画图（更快）
    python scripts/rebuild_all.py --library D:\\mine\\library   # 指定库（覆盖设置里的）

判定「需要重建」的依据（缺一不可，全部读本地文件，不联网）：
  · coach/<tag>.json 不存在，或没有 moves；
  · 状态文件 status 不是 ok（failed / partial / 缺失），除非明确 ok+no_bad_moves；
  · pipeline_version 与当前脚本不一致（旧版本字段不全）；
  · coach 里的 moves 数与状态里的 coach_moves 不一致；
  · moves 非空但存在空解读文本 / 坐标缺失比例过高。
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import paths as PATHS           # noqa: E402

# 先算「这个库是哪来的」再 apply：apply 会把结果写进 MC_LIB，
# 之后 describe() 看到的就是环境变量，来源会误报成「环境变量 MC_LIB」。
_ARGS = PATHS.parse_library_arg(sys.argv[1:])
LIB_DESC = PATHS.describe(_ARGS)
BASE, LIB = PATHS.apply(_ARGS)

import pipeline_one as P1     # noqa: E402

REPORT = LIB / "report"
COACH = LIB / "coach"
WORK = LIB / "work"

# 库锁句柄：拿到后一直持有，进程结束由系统释放
_LOCK = None


def load(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return None


def why_rebuild(tag):
    """返回需要重建的原因（空字符串 = 完好）。"""
    cp = COACH / f"{tag}.json"
    sp = COACH / f"{tag}.status.json"
    if not cp.exists():
        return "没有 coach 文件"
    coach = load(cp)
    if not isinstance(coach, dict):
        return "coach 文件读不出来"
    moves = coach.get("moves") or {}
    status = load(sp) if sp.exists() else None

    # 恶手门槛改过 → 已有的 bad_moves 是按旧门槛提的，必须重提（包括「本局无恶手」的局：
    # 门槛调低后它可能就有恶手了）
    if status:
        try:
            import badcfg as BC
            cur = BC.entry_thresh()
            used = status.get("bad_thresh", 0.10)      # v7 及更早固定 10pt
            if used is None or abs(float(used) - cur) > 1e-6:
                return f"门槛变了（{float(used) * 100:.0f}pt → {cur * 100:.0f}pt）"
        except Exception:
            pass

    if not moves:
        if status and status.get("status") == "ok" and status.get("no_bad_moves"):
            return ""                                  # 合法的「本局无恶手」
        if status and status.get("status") in ("failed", "partial"):
            return f"上次失败（{status.get('error_code')}）"
        return "没有解读（且无 ok+no_bad_moves 状态）"

    if not status:
        return "缺状态文件"

    if status.get("status") == "partial":
        return "上次只生成了一部分"
    if status.get("status") != "ok":
        return f"状态 {status.get('status')}（{status.get('error_code')}）"
    if status.get("pipeline_version") != P1.PIPELINE_VERSION:
        return f"版本过期（{status.get('pipeline_version')} → {P1.PIPELINE_VERSION}）"
    if status.get("coach_moves") not in (None, len(moves)):
        return f"moves 数不一致（coach {len(moves)} / 状态 {status.get('coach_moves')}）"
    empty = [k for k, v in moves.items() if not (v.get("text") or "").strip()]
    if empty:
        return f"{len(empty)} 手解读为空"
    miss = status.get("position_missing") or 0
    if len(moves) and miss / max(1, miss + len(moves)) > 0.2:
        return f"{miss}/{miss + len(moves)} 手没有坐标"
    wk = load(WORK / f"{tag}.json")
    if isinstance(wk, list):
        # 同一坐标可能有两条（立直回合），coach 按坐标去重，故比的是去重后的键数
        keys = {f"{r.get('kd_hand')}:{r.get('kd_ply')}" for r in wk
                if r.get("kd_hand") is not None and r.get("kd_ply") is not None}
        if len(keys) != len(moves):
            return f"中间结果与 coach 数量不一致（去重后 {len(keys)} / coach {len(moves)}）"
    return ""


def main():
    force = "--force" in sys.argv
    img = "--no-img" not in sys.argv
    # 一定把「实际写哪个库」说清楚：界面上改过库、BAT 又跑错库，是最难自查的一类问题
    print(LIB_DESC)
    # 写库前必须过锁闸：GUI 加了锁不等于别人不会绕过它来写。
    # 拿不到就一个字节都别写，退出码 3 让 BAT / 调用方知道是「库被占用」而不是「跑完了」。
    ok, handle, msg = PATHS.guard_writable(LIB, "重建")
    if not ok:
        print(msg, file=sys.stderr)
        raise SystemExit(3)
    globals()["_LOCK"] = handle          # 一直持有，进程结束由系统释放
    reps = sorted(REPORT.glob("*.json"))
    if not reps:
        print(f"{REPORT} 下没有报告。先在界面里分析一局，或把 Mortal 的 report json 放进去。")
        raise SystemExit(1)
    todo, ok_n = [], 0
    for rep in reps:
        tag = rep.stem
        if force:
            todo.append((rep, tag, "force"))
            continue
        why = why_rebuild(tag)
        if why:
            todo.append((rep, tag, why))
        else:
            ok_n += 1
    print(f"共 {len(reps)} 局报告：完好 {ok_n}，待处理 {len(todo)}"
          + (f" → {[t for _, t, _ in todo]}" if todo else ""))
    for _, t, why in todo:
        print(f"  · {t}: {why}")
    if not todo:
        print("全部已是最新，不用重建。")
        return

    t0 = time.time()
    fails = []
    for n, (rep, tag, why) in enumerate(todo, 1):
        print(f"\n=== [{n}/{len(todo)}] {tag}（{why}）===")
        try:
            st = P1.run(rep, tag, img=img)
        except Exception as e:
            print(f"  !! {tag} 抛异常：{type(e).__name__}: {e}")
            fails.append((tag, str(e)))
            continue
        if st.get("status") != "ok":
            fails.append((tag, st.get("error_message") or st.get("error_code") or "未知"))
    print(f"\n用时 {time.time() - t0:.0f} 秒。")
    if fails:
        print("以下局没有重建成功（按状态文件排查）：")
        for t, m in fails:
            print(f"  · {t}: {m}")
        raise SystemExit(1)
    print("全部完成。重新打开 mortal-coach 即可看到。")


if __name__ == "__main__":
    main()
