# -*- coding: utf-8 -*-
"""只重算解读文字 —— 恶手集合、牌桌坐标、牌型图都不动。

什么时候用：改了 explain.py / yakucalc.py 的**文案或判据**，但「哪些手是恶手」没变。
整条 pipeline 是 16~33 秒/局（要重新对齐 mjai_log、重画 PNG），而这里几秒钟就完事。

    python scripts/refresh_text.py                # 全部重算
    python scripts/refresh_text.py 261007 261118   # 只重算指定标签

输出与 pipeline 一致：更新 library/bad_moves.json、library/work/<标签>.json，
最后调 mk_coach.py 重新导出 coach/<标签>.json。
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(os.environ.get("MC_APP") or Path(__file__).resolve().parent.parent)
LIB = Path(os.environ.get("MC_LIB") or BASE / "library")
sys.path.insert(0, str(BASE / "scripts"))

import explain as X          # noqa: E402
import paths as PATHS        # noqa: E402

DATA = LIB / "bad_moves.json"
WORK = LIB / "work"
COACH = LIB / "coach"

# 库锁句柄：拿到后一直持有，进程结束由系统释放
_LOCK = None


def stamp_status(tags):
    """把参与重算的局的 status.pipeline_version 对齐到当前版本。"""
    try:
        from pipeline_one import PIPELINE_VERSION as V
    except Exception:
        return
    for g in tags:
        p = COACH / f"{g}.status.json"
        if not p.exists():
            continue
        try:
            st = json.load(open(p, encoding="utf-8"))
            if st.get("pipeline_version") != V:
                st["pipeline_version"] = V
                st["text_refreshed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                json.dump(st, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        except Exception:
            continue


def main(argv):
    tags = [a for a in argv[1:] if not a.startswith("-")]
    # 文字重算也会重写 bad_moves.json 与 coach/：同样要过锁闸
    ok, handle, msg = PATHS.guard_writable(LIB, "重算解读文字")
    if not ok:
        print(msg, file=sys.stderr)
        return 3
    globals()["_LOCK"] = handle
    if not DATA.exists():
        print(f"!! 找不到 {DATA}（先跑一次 pipeline_one / 一键重建解读）")
        return 1
    recs = json.load(open(DATA, encoding="utf-8"))
    if tags:
        recs = [r for r in recs if r.get("game") in set(tags)]
    if not recs:
        print("!! 没有可重算的记录")
        return 1

    t0 = time.time()
    ok = fail = 0
    errs = []
    for n, r in enumerate(recs, 1):
        try:
            tag, sev, txt = X.gen(r)
            if not (txt or "").strip():
                raise ValueError("解读为空")
            r["tag"], r["severity"], r["explain"] = tag, sev, txt
            ok += 1
        except Exception as e:                       # 一手失败不影响其他手
            fail += 1
            errs.append((r.get("game"), r.get("i"), f"{type(e).__name__}: {e}"))
        if n % 50 == 0 or n == len(recs):
            print(f"  解读 {n}/{len(recs)}（失败 {fail}）")

    # 写回总库：只替换本次重算过的局/手，其余原样保留
    if tags:
        keep = [r for r in json.load(open(DATA, encoding="utf-8"))
                if r.get("game") not in set(tags)]
        merged = keep + recs
    else:
        merged = recs
    json.dump(merged, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 逐局同步 work/<标签>.json（与 pipeline 的输出保持一致）
    WORK.mkdir(parents=True, exist_ok=True)
    by_tag = {}
    for r in merged:
        by_tag.setdefault(r.get("game"), []).append(r)
    for g, lst in by_tag.items():
        if tags and g not in set(tags):
            continue
        p = WORK / f"{g}.json"
        if p.exists():                       # 只更新已存在的，不凭空造局
            json.dump(lst, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"  写回 {DATA.name}（{len(merged)} 手，{time.time() - t0:.1f}s）")
    r = subprocess.run([sys.executable, str(BASE / "scripts" / "mk_coach.py")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    sys.stdout.write(r.stdout or "")
    if r.returncode != 0:
        sys.stdout.write(r.stderr or "")
        print("!! mk_coach 失败")
        return 1
    # 文字级重算同样是「本版本产物」：把状态文件的版本号一起更新，
    # 否则 rebuild_all 会以为这些局过期，白跑一遍整条流水线。
    stamp_status(set(tags) if tags else {r.get("game") for r in merged})
    if errs:
        print(f"  有 {len(errs)} 手失败：")
        for e in errs[:10]:
            print("   ", e)
    print(f"完成：成功 {ok} 手，失败 {fail} 手，用时 {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
