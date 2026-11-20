# -*- coding: utf-8 -*-
"""把 bad_moves.json 导出成回放器可直接查表的逐手解读数据。

输出（都在牌谱库里，默认 <程序目录>/library）：
  coach/<标签>.json   每局一份，key = "kd_hand:kd_ply"（与页面 GS.hand_counter/ply_counter 同源）
  coach/index.json    局列表 + rating，供侧栏下拉

不重算任何牌理：explain.py 生成的文字与 bad_moves.json 里的 kd_hand/kd_ply 直接复用。
"""
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

P = Path(os.environ.get("MC_APP") or Path(__file__).resolve().parent.parent)
LIB = Path(os.environ.get("MC_LIB") or P / "library")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import explain as X          # noqa: E402  只用来把整段文字切成「一页一个思考点」
import paths as PATHS        # noqa: E402
import yakucalc as YK        # noqa: E402  手牌分组（前端画「切法示意图」用）
# 导出会重写 coach/index.json：写之前先过锁闸。父进程（界面 / pipeline / refresh）
# 已经持锁时走授权路径，不会自己跟自己抢。
_OK, _LOCK, _MSG = PATHS.guard_writable(LIB, "导出 coach 数据")
if not _OK:
    print(_MSG, file=sys.stderr)
    raise SystemExit(3)
OUT = LIB / "coach"
OUT.mkdir(parents=True, exist_ok=True)


def web_img(p):
    """绝对路径 -> 服务根（assets/）下的相对 URL。"""
    if not p:
        return ""
    q = Path(p)
    if not q.exists():
        return ""
    return f"/{q.parent.name}/{q.name}"


def img_of(r):
    """对照图地址。`--no-img` 重跑时记录里可能没有 img_layout 字段，
    所以再按命名规则（{局}_{事件号:04d}.png）兜底找一次。"""
    u = web_img(r.get("img_layout"))
    if u:
        return u
    q = LIB / "img_layout" / f'{r.get("game")}_{int(r.get("i") or 0):04d}.png'
    return f"/img_layout/{q.name}" if q.exists() else ""


def hand_blocks(r):
    """两侧切法的「手牌示意图」数据：切哪张、切完的 13 张、分组、进张。"""
    out = {}
    for side, src in (("exp", "mortals"), ("act", "yours")):
        d = r.get(src) or {}
        ha = d.get("hand_after") or []
        if not ha:
            continue
        out[side] = {
            "cut": (r.get("exp_tile") if side == "exp" else r.get("act_tile")) or "",
            "hand": ha,
            "groups": YK.group_list(ha, r.get("calls") or 0),
            "shanten": d.get("shanten"),
            "uk": d.get("ukeire") or {},
            "imp": (r.get("improve") or {}).get(side) or {},
            "kinds": d.get("ukeire_kinds"),
            "tiles": d.get("ukeire_tiles"),
        }
    return out


def top_of(r):
    """Mortal 对每个候选的权重（softmax(Q/τ)），前端「候选评分」页直接用。

    top3 是 [[`dahai:7p`, 0.4899, -0.2539], …]，按权重从高到低。权重之和可能不足 1，
    因为只保留了前几个（其余是长尾），前端不要当成概率归一化。
    """
    out = []
    for it in (r.get("top3") or []):
        try:
            act, p, q = str(it[0]), float(it[1]), float(it[2])
        except (TypeError, ValueError, IndexError):
            continue
        kind, _, pai = act.partition(":")
        out.append({"act": kind, "pai": pai, "p": round(p, 4), "q": round(q, 4)})
    return out


recs = json.load(open(LIB / "bad_moves.json", encoding="utf-8"))
by_game = defaultdict(dict)
for r in recs:
    key = f'{r.get("kd_hand")}:{r.get("kd_ply")}'
    if key == "None:None":
        continue
    ql = None
    try:
        ql = round(float(r.get("Q_act")) - float(r.get("Q_exp")), 3)
    except (TypeError, ValueError):
        pass
    by_game[r["game"]][key] = {
        "tag": r.get("tag") or "",
        "sev": r.get("severity") or "",
        "gap": round(float(r.get("gap") or 0), 3),
        "pAct": round(float(r.get("P_act") or 0), 3),
        "pExp": round(float(r.get("P_exp") or 0), 3),
        "qloss": ql,
        "actual": r.get("act_tile") or "",
        "expect": r.get("exp_tile") or "",
        "text": r.get("explain") or "",
        "steps": X.steps_of(r.get("explain") or "", r.get("tag") or ""),
        "lesson": X.lesson_of(r.get("tag") or ""),
        "hands": hand_blocks(r),
        "top": top_of(r),
        "now": {
            "hand": r.get("tehai14") or [],
            "drawn": r.get("drawn") or "",
            "groups": YK.group_list(r.get("tehai14") or [], r.get("calls") or 0),
        },
        "img": img_of(r),
    }

# 局列表：report 目录下的 json 才是有效的可打开局
index = []
fails = []
for rp in sorted((LIB / "report").glob("*.json")):
    tag = rp.stem
    try:
        d = json.load(open(rp, encoding="utf-8"))
        rv = d.get("review") or {}
        rating = rv.get("rating")
        reviewed = rv.get("total_reviewed")
        matches = rv.get("total_matches")
        kyoku_n = len(rv.get("kyokus") or [])
        model = rv.get("model_tag") or ""
    except Exception as e:
        print(f"  跳过 {tag}: {e}")
        fails.append(tag)
        continue
    moves = by_game.get(tag, {})
    try:
        out_path = OUT / f"{tag}.json"
        tmp = OUT / f".{tag}.json.tmp"
        tmp.write_text(json.dumps({"game": tag, "rating": rating, "moves": moves},
                                  ensure_ascii=False), encoding="utf-8")
        tmp.replace(out_path)
    except Exception as e:
        print(f"  写 {tag} 失败: {e}")
        fails.append(tag)
        continue
    index.append({
        "tag": tag,
        "rating": round(rating * 100, 1) if isinstance(rating, (int, float)) else None,
        "reviewed": reviewed,
        "matches": matches,
        "kyoku": kyoku_n,
        "model": model,
        "bad": len(moves),
    })
    print(f"  {tag}: {len(moves)} 手解读, rating {index[-1]['rating']}")

index.sort(key=lambda x: x["tag"])
tmp = OUT / ".index.json.tmp"
tmp.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
tmp.replace(OUT / "index.json")
print(f"完成：{len(index)} 局，{sum(i['bad'] for i in index)} 手")
if fails:
    print("以下局有问题：" + ", ".join(fails))
    sys.exit(1)
