# -*- coding: utf-8 -*-
"""从**一份 Mortal 报告**里提取恶手（不需要任何外部清单）。

与早期的 extract_bad.py 的区别：
  那个脚本靠手写的 GAMES 清单（局名 / 牌谱 / 座位 三处各写一遍）；
  这里只要一份 report.json —— 座位读 `player_id`，牌谱读 `mjai_log`，
  评分条目读 `review.kyokus[*].entries`，全部都在报告文件里。

判定口径：我方动作 P 与 Mortal 最优动作 P 差 ≥ 门槛（`bad.thresh`，默认 10pt，
P = softmax(q/0.1)）就入库。门槛之上的手**全部算恶手**，只按权重差分两种颜色
（严重 ≥50pt 红 / 其余橙），不再有「轻微」这一档。
"""
import json
import math
from collections import Counter, defaultdict

import mjcalc

THRESH = 0.10


def akey(o):
    if not o:
        return None
    t = o.get("type")
    p = o.get("pai")
    return f"{t}:{p}" if t in ("dahai", "chi", "pon", "kan") else t


def probs(qmap, T=0.1):
    if not qmap:
        return {}
    mx = max(qmap.values())
    e = {k: math.exp(v / T - mx / T) for k, v in qmap.items()}
    s = sum(e.values())
    return {k: v / s for k, v in e.items()}


def key_of(h, t):
    return (tuple(sorted(h.items())), t)


def build_states(log):
    """index -> 场况快照（处理完第 i 个事件之后）"""
    st = {}
    pond = [[], [], [], []]
    melds = [[], [], [], []]
    riichi = [False] * 4
    dora = []
    scores = [25000] * 4
    bakaze, kyoku, honba = "E", 1, 0
    for i, e in enumerate(log):
        t = e.get("type")
        if t == "start_kyoku":
            pond = [[], [], [], []]
            melds = [[], [], [], []]
            riichi = [False] * 4
            dora = [e["dora_marker"]]
            scores = list(e["scores"])
            bakaze, kyoku, honba = e["bakaze"], e["kyoku"], e["honba"]
        elif t == "dora":
            dora.append(e["dora_marker"])
        elif t == "dahai":
            pond[e["actor"]].append(e["pai"])
        elif t in ("chi", "pon", "daiminkan", "ankan", "kakan"):
            a = e["actor"]
            melds[a].append({"type": t, "pai": e.get("pai"),
                             "consumed": list(e.get("consumed") or [])})
        elif t == "reach":
            riichi[e["actor"]] = True
        st[i] = {"pond": [list(x) for x in pond], "melds": [list(x) for x in melds],
                 "riichi": list(riichi), "dora": list(dora), "scores": list(scores),
                 "bakaze": bakaze, "kyoku": kyoku, "honba": honba}
    return st


def analyze_discard(hand, tile, calls=0, visible=None):
    """打出 tile 后：剩余手牌、向听、进张（考虑场上已见牌）"""
    h = list(hand)
    if tile not in h:
        return None
    h.remove(tile)
    vis = dict(visible or {})
    vis[tile] = vis.get(tile, 0) + 1      # 打出的这张已进牌河，摸不回来
    s, uk = mjcalc.ukeire(h, calls, vis)
    return {"hand_after": h, "shanten": s, "ukeire_kinds": len(uk),
            "ukeire_tiles": sum(uk.values()), "ukeire": uk, "calls": calls}


def visible_counter(st, hand=None):
    """场上可见牌（四家牌河 + 四家副露 + 宝牌指示牌）

    牌河快照保留着被鸣走的那张，与 melds 重复计数 → 用「4 − 手牌」封顶。
    """
    c = Counter()
    for p in st.get("pond") or []:
        c.update(p)
    for ml in st.get("melds") or []:
        for m in ml:
            for x in (m.get("consumed") or []):
                c[x] += 1
            if m.get("pai"):
                c[m["pai"]] += 1
    for d in st.get("dora") or []:
        if d and d != "?":
            c[d] += 1
    if hand:
        hc = Counter(hand)
        for t in list(c):
            cap = max(0, 4 - hc.get(t, 0))
            if c[t] > cap:
                c[t] = cap
    return c


def extract(log, rev, seat, game="", thresh=THRESH, stats=None):
    """返回该局的恶手记录列表。

    stats（可选 dict）：把对齐过程的计数填进去，用来区分「真的没有恶手」和
    「报告格式变了、全部对不上」——这两种情况在旧版本里都表现为空列表。
    """
    if stats is None:
        stats = {}
    stats.update({"entries": 0, "self": 0, "call": 0, "matched": 0,
                  "fingerprint_miss": 0, "dup": 0, "no_q": 0,
                  "threshold_filtered": 0, "bad": 0})
    states = build_states(log)
    # 指纹对齐：把手牌快照 → 事件下标
    hand = Counter()
    self_pts, call_pts = [], []
    for i, e in enumerate(log):
        t = e.get("type")
        if t == "start_kyoku":
            hand = Counter(e["tehais"][seat])
            continue
        if e.get("actor") == seat and isinstance(e.get("consumed"), list):
            for x in e["consumed"]:
                hand[x] -= 1
                if hand[x] <= 0:
                    del hand[x]
            if t in ("chi", "pon", "daiminkan", "ankan", "kakan"):
                self_pts.append((i, Counter(hand), e.get("pai") or e["consumed"][0]))
        if t == "tsumo" and e.get("actor") == seat:
            hand[e["pai"]] += 1
            self_pts.append((i, Counter(hand), e["pai"]))
        elif t == "dahai":
            if e.get("actor") == seat:
                hand[e["pai"]] -= 1
                if hand[e["pai"]] <= 0:
                    del hand[e["pai"]]
            else:
                call_pts.append((i, Counter(hand), e["pai"]))
    self_idx, call_idx = defaultdict(list), defaultdict(list)
    for i, h, t in self_pts:
        self_idx[key_of(h, t)].append(i)
    for i, h, t in call_pts:
        call_idx[key_of(h, t)].append(i)

    entries = [e for k in rev["kyokus"] for e in k["entries"]]
    stats["entries"] = len(entries)
    out = []
    last_used, used_keys = {}, set()
    for e in entries:
        k = key_of(Counter(e["state"]["tehai"]), e["tile"])
        kind = "self" if e["last_actor"] == seat else "call"
        stats[kind] = stats.get(kind, 0) + 1
        pool = self_idx.get(k) if kind == "self" else call_idx.get(k)
        if pool:
            i = pool.pop(0)
            last_used[(kind, k)] = i
            stats["matched"] += 1
        else:
            i = last_used.get((kind, k))
        if i is None:
            stats["fingerprint_miss"] += 1
            continue
        dk = (i, akey(e["expected"]))
        if dk in used_keys:          # 立直回合会被记两条
            stats["dup"] += 1
            continue
        used_keys.add(dk)

        qmap = {}
        for d in e.get("details", []):
            o = d["action"]
            qmap[akey(o)] = d["q_value"]
        Pp = probs(qmap)
        eb, ab = akey(e["expected"]), akey(e["actual"])
        if eb not in Pp or ab not in Pp:
            stats["no_q"] += 1
            continue
        gap = Pp[eb] - Pp[ab]
        if gap < thresh:
            stats["threshold_filtered"] += 1
            continue

        tehai = list(e["state"]["tehai"])
        drawn = e["tile"]
        calls = len(e["state"].get("fuuros") or [])
        hand13 = list(tehai)
        if e["last_actor"] == seat and not e.get("at_self_chi_pon") and drawn in hand13:
            hand13.remove(drawn)
        st = states.get(i, {})
        act_tile = e["actual"].get("pai")
        if e["actual"].get("type") == "reach":
            for j in range(i + 1, min(i + 6, len(log))):
                if log[j].get("type") == "dahai" and log[j].get("actor") == seat:
                    act_tile = log[j]["pai"]
                    break
        exp_tile = e["expected"].get("pai")
        rec = {
            "game": game, "i": i, "seat": seat,
            "kyoku": f"{st.get('bakaze', '?')}{st.get('kyoku', '?')}局{st.get('honba', 0)}本场",
            "junme": e["junme"], "tiles_left": e["tiles_left"],
            "hand13": hand13, "drawn": drawn, "tehai14": tehai, "calls": calls,
            "shanten_before": e.get("shanten"),
            "fuuro_self": e["state"].get("fuuros", []),
            "ponds": st.get("pond"), "melds": st.get("melds"), "riichi": st.get("riichi"),
            "dora": st.get("dora"), "scores": st.get("scores"),
            "expected": e["expected"], "actual": e["actual"],
            "P_exp": Pp[eb], "P_act": Pp[ab], "gap": gap,
            "Q_exp": qmap[eb], "Q_act": qmap[ab],
            "top3": sorted([(k2, Pp[k2], qmap[k2]) for k2 in qmap],
                           key=lambda z: -z[2])[:4],
            "act_tile": act_tile, "exp_tile": exp_tile,
            "mode": ("self_draw" if (e["last_actor"] == seat and not e.get("at_self_chi_pon"))
                     else ("post_call" if e.get("at_self_chi_pon") else "call_window")),
            "at_furiten": e.get("at_furiten"),
            "cls": ("打牌" if e["expected"].get("type") == "dahai" else
                    ("鸣牌窗" if e["expected"].get("type") == "none"
                     else e["expected"].get("type"))),
        }
        vis = visible_counter(st, tehai)
        if act_tile and e["actual"].get("type") in ("dahai", "reach") and act_tile in tehai:
            rec["yours"] = analyze_discard(tehai, act_tile, calls, vis)
        if exp_tile and e["expected"].get("type") in ("dahai", "reach") and exp_tile in tehai:
            rec["mortals"] = analyze_discard(tehai, exp_tile, calls, vis)
        out.append(rec)
    stats["bad"] = len(out)
    return out


def build_positions(mjai_log):
    """全局事件下标 -> killerducky 牌桌坐标 (hand, ply)，与 index.js parseMortalJsonStr 一致。"""
    pos, hand, ply = {}, -1, 0
    for idx, e in enumerate(mjai_log):
        t = e.get("type")
        if t in ("end_game", "start_game", "dora"):
            continue
        if t == "start_kyoku":
            hand += 1
            ply = 0
            continue
        if t == "end_kyoku":
            continue
        pos[idx] = (hand, ply)
        ply += 1
    return pos


def load_report(path):
    """读报告，返回 (log, review, seat)。座位优先取 player_id，缺了就按「entries 里 actor 最多」猜。"""
    d = json.load(open(path, encoding="utf-8"))
    log = d.get("mjai_log") or (d.get("review") or {}).get("mjai_log") or []
    rev = d.get("review") or {}
    seat = d.get("player_id")
    if seat is None:
        seat = (rev.get("player_id") if isinstance(rev.get("player_id"), int) else None)
    if seat is None:
        c = Counter()
        for k in rev.get("kyokus") or []:
            for e in k.get("entries") or []:
                a = e.get("actual") or {}
                if isinstance(a.get("actor"), int):
                    c[a["actor"]] += 1
        seat = c.most_common(1)[0][0] if c else None
    return log, rev, seat
