# -*- coding: utf-8 -*-
"""役种走向与打点估算 —— 给「局面」页提供「这手牌在做什么」的前提说明。

为什么需要它：牌效率只回答「哪张进张多」，但同样的进张在
「断幺 + 平和 2000 点」和「混一色 8000 点」两条路线下价值完全不同。
决定路线的三件事是——**手牌形状能成什么役 / 现在几点几顺位需要多少打点 /
宝牌有几张**。前两件在这里算。

口径（谨慎，不夸大）：
  · progress = 该役的「完成度」，0~1。只有 ≥0.75 才写成「主线」，
    0.5~0.75 写成「备选」，低于 0.5 不写。
  · 番数是**该役本身的番**，不含立直/自摸/门清荣和，也不叠加
    （断幺+平和会叠加，这是叠过的；断幺+混一色不会同时成立，按互斥分组）。
  · 点数按 30 符、子家/亲家查表，只写「约」。

互斥分组：一副手牌只能选一种「牌型路线」，同组内取最高的那条。
  G_YAKU  断幺 / 混一色 / 清一色 / 役牌 / 七对子（只能选一）
  附加    平和 / 一气通贯 / 三色同顺 / 一杯口（可以和上面的叠加）
"""
from collections import Counter

import mjeval as E

SUIT_CN = {"m": "万", "p": "筒", "s": "索"}
KT = ["P", "F", "C"]


def _norm(t):
    if not t:
        return t
    if t[0] == "0":
        return "5" + t[1]
    if len(t) == 3 and t[2] == "r":
        return t[0] + t[1]
    return t


def _suit_of(t):
    """'1m'→'m'，'E'→'z'（字牌在 mjai 里是单字符）。"""
    return t[1] if len(t) > 1 and t[1] in "mps" else "z"


def _honor(t):
    return _suit_of(t) == "z"


def _terminal(t):
    return (not _honor(t)) and t[0] in "19"


def all_tiles(hand, melds=None):
    ts = [_norm(t) for t in (hand or [])]
    for m in (melds or []):
        for x in m.get("consumed") or []:
            ts.append(_norm(x))
        if m.get("pai"):
            ts.append(_norm(m["pai"]))
    return ts


def pt_of(han, dealer=False, fu=30):
    """30 符的粗算点数（子家 / 亲家）。只用于「约 X 点」的口气。"""
    if han <= 0:
        return 0
    table = {1: (1000, 1500), 2: (2000, 2900), 3: (3900, 5800), 4: (7700, 11600),
             5: (8000, 12000), 6: (12000, 18000), 7: (12000, 18000),
             8: (16000, 24000), 9: (16000, 24000), 10: (16000, 24000),
             11: (24000, 36000), 12: (24000, 36000), 13: (32000, 48000)}
    if han in table:
        c, p = table[han]
        return p if dealer else c
    if han > 13:
        return 48000 if dealer else 32000
    return 0


def han_for(delta, dealer=False):
    """需要多少番才能cover delta 点（子家/亲家，30 符）。返回最小番数，或 None。"""
    for h in range(1, 14):
        if pt_of(h, dealer) >= delta:
            return h
    return None


def dora_count(tiles, dora_markers):
    ds = E.dora_set(dora_markers)
    c = Counter(tiles)
    return sum(c[t] for t in ds if t in c), sorted(ds)


def _seq_ok(c, s, n):
    """花色 s 是否还能凑出 n,n+1,n+2（只要各有 1 张就算「在路上」）。"""
    return all(c.get(f"{x}{s}", 0) >= 1 for x in (n, n + 1, n + 2))


def routes(hand, melds=None, seat_wind="E", round_wind="E",
           dora_markers=None, menzen=None):
    """返回候选路线列表，按 (组, progress) 排好序。"""
    tiles = all_tiles(hand, melds)
    c = Counter(tiles)
    n = max(1, len(tiles))
    calls = len(melds or [])
    if menzen is None:
        menzen = (calls == 0)
    out = []
    # 手牌的最优 5-block 分解：判断「对对和」这类路线可行性时要看顺子有几组
    st = E.analyze_struct(list(hand or []), calls=calls, cap=99)

    # ---------- 牌型组（互斥） ----------
    # 断幺九
    bad = [t for t in c if _terminal(t) or _honor(t)]
    tan_n = n - sum(c[t] for t in bad)
    if not bad:
        tan_why = "已全 2~8"
    elif len(bad) <= 2:
        tan_why = "切掉 " + "、".join(E.zh(t) for t in sorted(bad)) + " 即可"
    else:
        tan_why = f"手上还有 {len(bad)} 种幺九/字牌要清"
    out.append(dict(g="A", name="断幺九", han=1, prog=tan_n / n, why=tan_why))
    # 混一色 / 清一色
    hon = sum(v for t, v in c.items() if _honor(t))
    for s in "mps":
        k = sum(v for t, v in c.items() if _suit_of(t) == s)
        prog = k / n
        if prog < 0.5:
            continue
        if k >= n - 1 and hon <= 1:      # 差一张就清一色
            out.append(dict(g="A", name="清一色", han=(6 if menzen else 5), prog=min(1.0, prog),
                            why=f"{SUIT_CN[s]}子 {k}/{n} 张"))
        else:
            out.append(dict(g="A", name="混一色", han=(3 if menzen else 2), prog=prog,
                            why=f"{SUIT_CN[s]}子 {k}/{n} 张，字牌 {hon} 张"))
    # 役牌
    ys = list(dict.fromkeys(KT + [w for w in (seat_wind, round_wind) if w]))
    for t in ys:
        k = c.get(t, 0)
        if k < 2:
            continue
        out.append(dict(g="A", name=f"役牌 {E.zh(t)}", han=1,
                        prog=(1.0 if k >= 3 else 0.62),
                        why=("已成刻子" if k >= 3 else "有对子，碰或摸成刻子即 1 番")))
    # 七对子
    npair = sum(v // 2 for v in c.values())      # 4 张算 2 对，刻子也可拆 1 对
    if menzen:
        if npair >= 4:
            out.append(dict(g="A", name="七对子", han=2, prog=npair / 7.0,
                            why=f"{npair} 个对子（要 7 个）"))
    # 对对和：手里还摆着顺子时，这不是「一条路」，是要先把顺子拆掉——
    # 完成度压到 0.45 以下，只当备注（best() 要求 prog ≥ 0.55 才算主线）。
    trip = sum(1 for v in c.values() if v >= 3)
    pairs = npair
    if trip >= 2 and pairs >= 1:
        seq_now = sum(1 for g in st["groups"] if g[0] == "顺子")
        prog2 = min(1.0, (trip + 0.5) / 4.0)
        if seq_now:
            prog2 = min(prog2, 0.45)
            why2 = f"刻子 {trip} 组、对子 {pairs} 组，但手里有 {seq_now} 组顺子，走对对和要先拆"
        else:
            why2 = f"刻子 {trip} 组、对子 {pairs} 组"
        out.append(dict(g="A", name="对对和", han=2, prog=prog2, why=why2))

    # ---------- 附加役（可与牌型组叠加） ----------
    has_trip = any(g[0] == "刻子" for g in st["groups"])
    seq_n = sum(1 for g in st["groups"] if g[0] == "顺子")
    if menzen and not has_trip and seq_n >= 1:
        out.append(dict(g="B", name="平和", han=1, prog=seq_n / 4.0,
                        why=f"顺子 {seq_n} 组、无刻子"))

    # 一气通贯
    for s in "mps":
        seg = sum(1 for b in (1, 4, 7) if _seq_ok(c, s, b))
        if seg >= 2:
            out.append(dict(g="B", name="一气通贯", han=(2 if menzen else 1), prog=seg / 3.0,
                            why=f"{SUIT_CN[s]}子占了 {seg}/3 段"))
    # 三色同顺
    best3, bestn = 0, None
    for k in range(2, 9):
        got = sum(1 for s in "mps" if _seq_ok(c, s, k - 1))
        if got > best3:
            best3, bestn = got, k
    if best3 >= 2:
        out.append(dict(g="B", name="三色同顺", han=(2 if menzen else 1), prog=best3 / 3.0,
                        why=f"{bestn}-{bestn + 1}-{bestn + 2} 有三个花色中的 {best3} 个"))
    # 一杯口
    if menzen:
        reps = 0
        for s in "mps":
            for k in range(1, 8):
                if all(c.get(f"{x}{s}", 0) >= 2 for x in (k, k + 1, k + 2)):
                    reps += 1
        if reps:
            out.append(dict(g="B", name="一杯口", han=1, prog=1.0, why="同色同顺子两组"))

    # 宝牌（不算役，但算番）
    nd, _ = dora_count(tiles, dora_markers)
    for r in out:
        r["dora"] = nd
    return out


def _val(r):
    """路线的「值」= 完成度 × 该番数对应的点数。避免「断幺 1000 点」压过「混一色 3900 点」。"""
    return r["prog"] * max(1, pt_of(r["han"]))


def best(routes_):
    """挑「主线」：A 组（互斥牌型）里取值最高的；再叠加 B 组里 progress ≥0.72 的最高番。"""
    A = [r for r in routes_ if r["g"] == "A" and r["prog"] >= 0.55]
    B = [r for r in routes_ if r["g"] == "B" and r["prog"] >= 0.72]
    main = None
    if A:
        main = max(A, key=_val)
    if main is None:
        return None, []
    combo = [main]
    if B:
        b = max(B, key=lambda r: (r["han"], r["prog"]))
        if b is not main:
            combo.append(b)
    return main, combo


def outline(hand, melds=None, seat_wind="E", round_wind="E",
            dora_markers=None, dealer=False, menzen=None):
    """一句话的「做牌前提」。返回 dict：
    {main, han, pt, dora, text, prog, names}
    """
    rs = routes(hand, melds, seat_wind, round_wind, dora_markers, menzen)
    main, combo = best(rs)
    nd, _ = dora_count(all_tiles(hand, melds), dora_markers)
    if main is None:
        return dict(main="", han=0, pt=0, dora=nd, prog=0.0, names=[],
                    text="手牌还没有明显役线（幺九字牌偏多），先按牌效推进，边走边定。")
    names = [r["name"] for r in combo]
    han = sum(r["han"] for r in combo) + nd
    pt = pt_of(han, dealer)
    prog = main["prog"]
    lvl = ("基本成形" if prog >= 0.88 else
           ("八成" if prog >= 0.72 else "只是倾向，还要看进张"))
    s = f"走「{' + '.join(names)}」这条线，{lvl}"
    s += f"（成型后 {han} 番"
    s += f"，约 {pt} 点" if pt else ""
    s += f"，宝牌 {nd} 张）" if nd else "）"
    s += f"。{main['why']}。"
    # 备选：另一条同组但番更高、进度 0.45~0.72 的路
    alts = [r for r in rs if r["g"] == "A" and r is not main
            and 0.65 <= r["prog"] < 0.85 and r not in combo
            and r["han"] > main["han"]]
    if alts:
        a = max(alts, key=lambda r: r["prog"])
        s += f"备选「{a['name']}」（{a['han']} 番）：{a['why']}。"
    return dict(main=main["name"], han=han, pt=pt, dora=nd, prog=prog,
                names=names, text=s)


def outline_line(hand, melds=None, seat_wind="E", round_wind="E",
                 dora_markers=None, dealer=False, menzen=None):
    return outline(hand, melds, seat_wind, round_wind,
                   dora_markers, dealer, menzen)["text"]


# ---------------- 点数 / 顺位 ----------------
ORDER = ["我方", "下家", "对家", "上家"]


def score_lines(scores, seat, kyoku="", honba=0):
    """返回 (点数行, 顺位行)。scores 按绝对座次；seat 是我方绝对座次。"""
    if not scores or len(scores) < 4 or seat is None:
        return None, None
    rel = [(scores[(seat + i) % 4], ORDER[i]) for i in range(4)]
    rank = {}
    for i, (sc, name) in enumerate(rel):
        rank[name] = 1 + sum(1 for j, (v, _) in enumerate(rel)
                             if v > sc or (v == sc and j < i))
    flat = len(set(sc for sc, _ in rel)) == 1
    if flat:
        s1 = "点数：" + " · ".join(f"{nm} {sc}" for sc, nm in rel) + "（平场）"
        return s1, "顺位：平场，没有顺位压力，按牌效与牌型正常推进。"

    s1 = "点数：" + " · ".join(f"{nm} {sc}（{rank[nm]}位）" for sc, nm in rel)
    me = dict((nm, sc) for sc, nm in rel)["我方"]
    others = sorted([(sc, nm, rank[nm]) for sc, nm in rel if nm != "我方"],
                    key=lambda z: -z[0])
    my_rank = rank["我方"]
    last = (kyoku or "")[:2] == "S4"          # 半庄的最后一局
    parts = []
    if my_rank == 1:
        gap = me - others[0][0]
        parts.append(f"领先二位（{others[0][1]}）{gap} 点")
        if gap >= 12000:
            parts.append("一位很稳，首要是不放铳")
        elif gap >= 5000:
            parts.append("一位但别放松，被追立要慎重")
        else:
            parts.append("一位很薄，随时可能被翻，该争就争")
        if last:
            parts.append("南4局，守住这个点数即可")
    else:
        up = [z for z in others if z[2] == my_rank - 1]
        up_sc, up_nm, up_rk = up[0]
        gap = up_sc - me
        h = han_for(gap)
        parts.append(f"距 {up_rk} 位（{up_nm}）{gap} 点")
        if my_rank == 4:
            parts.append(f"四位，需要 {h} 番的和牌" if h and h <= 6 else "四位，需要满贯以上的大牌")
        elif my_rank == 3:
            parts.append(f"三位，先保底（{h} 番可反超）" if h else "三位，先保底")
        else:
            parts.append(f"二位，{h} 番可反超一位" if h else "二位，守住即可")
        if last:
            parts.append("南4局，这是最后的机会")
    s2 = "顺位：" + "，".join(parts) + "。"
    return s1, s2


# ---------------- 手牌分组（给前端画「切法示意图」） ----------------
GORDER = {"顺子": 0, "刻子": 0, "两面": 1, "嵌张": 1, "边张": 1, "对子": 2}


def group_list(hand, calls=0):
    """按 5-block 分解把手牌拆成 [[标签, [牌...]], ...]；剩下的算浮牌。
    返回的是「打完这张之后」的 13 张，前端按组画牌。"""
    hand = list(hand or [])
    if not hand:
        return []
    st = E.analyze_struct(hand, calls=calls, cap=99)
    pool = Counter(E.t2i(t) for t in hand)
    seq = []
    for lab, g in sorted(st["groups"], key=lambda z: GORDER.get(z[0], 9)):
        ts = []
        for x in g:
            if pool.get(x, 0) > 0:
                pool[x] -= 1
                ts.append(E.i2t(x))
        if ts:
            seq.append([lab, ts])
    rest = []
    for x in sorted(pool):
        rest += [E.i2t(x)] * pool[x]
    if rest:
        seq.append(["浮牌", rest])
    return seq
