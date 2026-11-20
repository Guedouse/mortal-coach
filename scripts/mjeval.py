# -*- coding: utf-8 -*-
"""日麻牌理分析引擎（解读用）。

提供：
  shanten / ukeire            —— 复用 mjcalc
  waits_with_shape            —— 听牌 + 待牌形（两面/嵌张/边张/单骑/双碰/多面）
  best_tenpai                 —— 14 张手牌的最优听牌（打哪张、听什么）
  good_shape_rate             —— 好形率（有效牌里能通向两面听的比例）
  describe_hand               —— 手牌结构（顺子/刻子/对子/两面/嵌张/边张/孤张）
  yaku_info                   —— 断幺 / 平和 / 役牌 / 宝牌 / 对子数
  safety_grade                —— 对某一家的安全度等级（现物/筋/无筋…）
"""
from collections import Counter
from mjcalc import t2i, i2t, counts_of, shanten, ukeire, HONORS

SUIT_OF = {"m": 0, "p": 1, "s": 2}
SUITCN = {"m": "万", "p": "筒", "s": "索"}
HON_ZH = {"E": "东", "S": "南", "W": "西", "N": "北", "P": "白", "F": "发", "C": "中"}


def to_tiles(c):
    ts = []
    for i in range(34):
        ts += [i2t(i)] * c[i]
    return ts


def zh(t):
    if not t:
        return ""
    if t in HON_ZH:
        return HON_ZH[t]
    base = t[0] + SUITCN[t[1]]
    if len(t) == 3 and t[2] == "r":
        return base + "(赤)"
    if t[0] == "0":
        return "5" + SUITCN[t[1]] + "(赤)"
    return base


def show(ts):
    return " ".join(zh(t) for t in ts)


# ---------------- 和牌形分解 ----------------
def decomp(c, calls=0):
    """把 (14 - 3*calls) 张手牌分解为 (4-calls) 面子 + 雀头 的全部方式。c 会被就地修改后还原。"""
    need_m = 4 - calls
    out = []
    acc = []

    def dfs(i, mleft, need_pair):
        while i < 34 and c[i] == 0:
            i += 1
        if i == 34:
            if mleft == 0 and not need_pair:
                out.append(list(acc))
            return
        if c[i] >= 3 and mleft > 0:
            c[i] -= 3
            acc.append(("m", (i, i, i)))
            dfs(i, mleft - 1, need_pair)
            acc.pop()
            c[i] += 3
        if i < 27 and i % 9 <= 6 and c[i + 1] and c[i + 2] and mleft > 0:
            c[i] -= 1; c[i + 1] -= 1; c[i + 2] -= 1
            acc.append(("m", (i, i + 1, i + 2)))
            dfs(i, mleft - 1, need_pair)
            acc.pop()
            c[i] += 1; c[i + 1] += 1; c[i + 2] += 1
        if c[i] >= 2 and need_pair:
            c[i] -= 2
            acc.append(("p", (i, i)))
            dfs(i, mleft, False)
            acc.pop()
            c[i] += 2

    dfs(0, need_m, True)
    return out


def _shape_of(c, calls, w):
    """c 已是「含 w 的和牌形」，判断 w 是以什么形和的。"""
    shapes = set()
    for d in decomp([x for x in c], calls):
        for kind, g in d:
            if kind == "m":
                if g[0] == g[1] == g[2]:
                    if g[0] == w:
                        shapes.add("双碰")
                else:
                    if w in g:
                        rest = [x for x in g if x != w]
                        if len(rest) == 2:
                            a, b = rest
                            if b - a == 1:
                                shapes.add("边张" if a == 0 or a == 7 else "两面")
                            else:
                                shapes.add("嵌张")
            else:
                if g[0] == w:
                    shapes.add("单骑")
    order = {"单骑": 1, "双碰": 2, "边张": 3, "嵌张": 4, "两面": 5, "多面": 6}
    if not shapes:
        return "单骑"
    return max(shapes, key=lambda s: order[s])


def waits_with_shape(hand13, calls=0, visible=None):
    """13 张手牌若已听牌：返回 {待牌: (形, 场见剩余枚数)}。"""
    c = counts_of(hand13)
    vis = [0] * 34
    for t, n in (visible or {}).items():
        vis[t2i(t)] += n
    res = {}
    for w in range(34):
        if c[w] + vis[w] >= 4:
            continue
        c[w] += 1
        ok = shanten(to_tiles(c), calls) == -1
        if ok:
            remain = 4 - (c[w] - 1) - vis[w]
            res[i2t(w)] = (_shape_of(list(c), calls, w), remain)
        c[w] -= 1
    return res


def best_tenpai(hand14, calls=0, visible=None):
    """14 张手牌：返回 (可和枚数, 待牌种数, 打哪张, {待牌:(形,枚数)})，取可和枚数最多的一打。"""
    best = None
    for d in sorted(set(hand14), key=lambda t: hand14.index(t)):
        h = list(hand14)
        h.remove(d)
        if shanten(h, calls) != 0:
            continue
        w = waits_with_shape(h, calls, visible)
        cnt = sum(v[1] for v in w.values())
        kinds = len(w)
        shape_rank = max(({"单骑": 1, "双碰": 2, "边张": 3, "嵌张": 4, "两面": 5}.get(v[0], 3)
                          for v in w.values()), default=0)
        key = (cnt, kinds, shape_rank)
        if best is None or key > best[0]:
            best = (key, cnt, kinds, d, w)
    if best is None:
        return None
    _, cnt, kinds, d, w = best
    return (cnt, kinds, d, w)


def _hand_shapes(waits):
    return set(v[0] for v in waits.values())


def good_shape_rate(hand, calls=0, visible=None):
    """好形率。hand 为 13 张（含副露则更少）。

    - 已听牌(0 向听)：直接看待牌形，两面/多面即为好形。
    - 一向听：摸到有效牌即听牌，看好形听牌的枚数占比。
    - 两向听及以上：无法一步到听牌，返回 None（解读改看进张与牌型）。
    """
    s, uk = ukeire(hand, calls, visible)
    if s == 0:
        w = waits_with_shape(hand, calls, visible)
        sh = _hand_shapes(w)
        gt = sum(v[1] for k, v in w.items()
                 if v[0] in ("两面", "多面") or len(w) >= 3)
        tt = sum(v[1] for v in w.values())
        return {"shanten": 0, "good_tiles": gt, "total_tiles": tt,
                "good_kinds": sum(1 for v in w.values() if v[0] in ("两面", "多面")),
                "total_kinds": len(w), "details": [], "waits": w,
                "rate": (gt / tt if tt else 0.0)}
    if s >= 2:
        return None
    gt = tt = gk = tk = 0
    details = []
    for u, n in uk.items():
        bt = best_tenpai(list(hand) + [u], calls, visible)
        if not bt:
            continue
        cnt, kinds, d, waits = bt
        sh = _hand_shapes(waits)
        good = ("两面" in sh) or ("多面" in sh) or len(waits) >= 3
        tt += n
        tk += 1
        if good:
            gt += n
            gk += 1
        details.append({"tile": u, "n": n, "discard": d, "shapes": sorted(sh),
                        "waits": {k: v for k, v in waits.items()}})
    return {"shanten": s, "good_tiles": gt, "total_tiles": tt,
            "good_kinds": gk, "total_kinds": tk, "details": details,
            "rate": (gt / tt if tt else 0.0)}


# ---------------- 最优牌型分解（5 block 理论） ----------------
def analyze_struct(hand, calls=0, cap=None):
    """按 5-block 理论求「面子最多、其次两面最多」的分解，返回各类型数量 + 分组牌面。
    cap=None 时按 5 组牌截断；cap 给大数则不截断（用于判断每张牌的角色）。"""
    c = counts_of(hand)
    total = sum(c)
    CAP = cap if cap is not None else (5 - calls)
    best = [None]

    def key(melds, ryan, kan, pen, pairs, used):
        iso = total - used
        return (melds, ryan, kan, pen, pairs, -iso)

    def rec(i, melds, ryan, kan, pen, pairs, acc):
        j = i
        while j < 34 and c[j] == 0:
            j += 1
        used = 3 * melds + 2 * (ryan + kan + pen + pairs)
        if j == 34 or (melds + ryan + kan + pen + pairs) >= CAP:
            k = key(melds, ryan, kan, pen, pairs, used)
            if best[0] is None or k > best[0][0]:
                best[0] = (k, list(acc), iso_of(total, used))
            return
        i = j
        if c[i] >= 3:
            c[i] -= 3; acc.append(("刻子", [i, i, i]))
            rec(i, melds + 1, ryan, kan, pen, pairs, acc)
            acc.pop(); c[i] += 3
        if i < 27 and i % 9 <= 6 and c[i + 1] and c[i + 2]:
            c[i] -= 1; c[i + 1] -= 1; c[i + 2] -= 1; acc.append(("顺子", [i, i + 1, i + 2]))
            rec(i, melds + 1, ryan, kan, pen, pairs, acc)
            acc.pop(); c[i] += 1; c[i + 1] += 1; c[i + 2] += 1
        if c[i] >= 2:
            c[i] -= 2; acc.append(("对子", [i, i]))
            rec(i, melds, ryan, kan, pen, pairs + 1, acc)
            acc.pop(); c[i] += 2
        if i < 27 and i % 9 <= 7 and c[i + 1]:
            r = i % 9
            lab = "边张" if (r == 0 or r == 7) else "两面"
            c[i] -= 1; c[i + 1] -= 1; acc.append((lab, [i, i + 1]))
            if lab == "两面":
                rec(i, melds, ryan + 1, kan, pen, pairs, acc)
            else:
                rec(i, melds, ryan, kan, pen + 1, pairs, acc)
            acc.pop(); c[i] += 1; c[i + 1] += 1
        if i < 27 and i % 9 <= 6 and c[i + 2]:
            c[i] -= 1; c[i + 2] -= 1; acc.append(("嵌张", [i, i + 2]))
            rec(i, melds, ryan, kan + 1, pen, pairs, acc)
            acc.pop(); c[i] += 1; c[i + 2] += 1
        # 留作孤张
        c[i] -= 1
        rec(i, melds, ryan, kan, pen, pairs, acc)
        c[i] += 1

    rec(0, 0, 0, 0, 0, 0, [])
    melds, ryan, kan, pen, pairs, _ = best[0][0]
    groups = best[0][1]
    iso = best[0][2]
    return {"melds": melds, "ryanmen": ryan, "kanchan": kan, "penchan": pen,
            "pairs": pairs, "isolated": iso, "groups": groups,
            "text": _groups_text(groups, iso)}


def iso_of(total, used):
    return total - used


_ROLE_LABEL = {"顺子": "顺子的一部分", "刻子": "刻子的一部分", "对子": "对子",
               "两面": "两面搭子的一部分", "嵌张": "嵌张搭子的一部分",
               "边张": "边张搭子的一部分"}


def role_of(hand, tile, calls=0):
    """这张牌在【最优分解】里属于什么块；不在任何块里 → 孤张。"""
    if tile is None:
        return "孤张"
    st = analyze_struct(hand, calls, cap=99)
    ti = t2i(tile)
    for lab, g in st["groups"]:
        if ti in g:
            return _ROLE_LABEL.get(lab, lab)
    return "孤张字牌" if tile in HON_ZH else "孤张"


def _groups_text(groups, iso):
    order = {"顺子": 0, "刻子": 1, "对子": 2, "两面": 3, "嵌张": 4, "边张": 5}
    gs = sorted(groups, key=lambda x: order.get(x[0], 9))
    parts = []
    for lab, g in gs:
        parts.append(f"{show([i2t(x) for x in g])}{lab}")
    txt = "、".join(parts)
    if iso:
        txt += f"（另有 {iso} 张散牌）"
    return txt


# ---------------- 手牌结构描述 ----------------
def _n_left(c, i):
    """i 这张牌的靠张种类数（不算牌山可见）。"""
    if i >= 27:
        return 0
    r = i % 9
    k = 0
    for d in (-2, -1, 1, 2):
        j = r + d
        if 0 <= j <= 8:
            k += 1
    return k


def describe_hand(hand, calls=0):
    """把手牌拆成可视结构：刻子/顺子/对子/两面/嵌张/边张/孤张。返回 [(标签, [牌])]。"""
    c = counts_of(hand)
    groups = []
    # 刻子
    for i in range(34):
        while c[i] >= 3:
            c[i] -= 3
            groups.append(("刻子", [i, i, i]))
    # 顺子
    for i in range(27):
        if i % 9 <= 6:
            while c[i] > 0 and c[i + 1] > 0 and c[i + 2] > 0:
                c[i] -= 1; c[i + 1] -= 1; c[i + 2] -= 1
                groups.append(("顺子", [i, i + 1, i + 2]))
    # 对子
    for i in range(34):
        while c[i] >= 2:
            c[i] -= 2
            groups.append(("对子", [i, i]))
    # 两面 / 边张（连张）
    for i in range(27):
        if i % 9 <= 7:
            while c[i] > 0 and c[i + 1] > 0:
                c[i] -= 1; c[i + 1] -= 1
                lab = "边张" if (i % 9 == 0 or i % 9 == 7) else "两面"
                groups.append((lab, [i, i + 1]))
    # 嵌张（隔张）
    for i in range(27):
        if i % 9 <= 6:
            while c[i] > 0 and c[i + 2] > 0:
                c[i] -= 1; c[i + 2] -= 1
                groups.append(("嵌张", [i, i + 2]))
    # 孤张
    for i in range(34):
        while c[i] > 0:
            c[i] -= 1
            n = _n_left(c, i)
            groups.append(("孤张" if n == 0 else "孤张", [i]))
    return [(lab, [i2t(x) for x in g]) for lab, g in groups]


def structure_str(hand, calls=0):
    gs = describe_hand(hand, calls)
    order = {"顺子": 0, "刻子": 1, "对子": 2, "两面": 3, "嵌张": 4, "边张": 5, "孤张": 6}
    gs.sort(key=lambda x: order.get(x[0], 9))
    parts = []
    for lab, ts in gs:
        if lab == "孤张":
            parts.append(f"{show(ts)}孤张")
        else:
            parts.append(f"{show(ts)}{lab}")
    return "、".join(parts)


# ---------------- 打点 / 役 ----------------
def _next_tile(t):
    if not t or t == "?":
        return None
    if t in HON_ZH:
        o = ["E", "S", "W", "N"]
        if t in o:
            return o[(o.index(t) + 1) % 4]
        o3 = ["P", "F", "C"]
        return o3[(o3.index(t) + 1) % 3]
    n, s = int(t[0]), t[1]
    return f"{n % 9 + 1}{s}"


def dora_set(markers):
    s = set()
    for m in markers or []:
        nx = _next_tile(m)
        if nx:
            s.add(nx)
    return s


def _is_red(t):
    return (len(t) == 3 and t[2] == "r") or (t[0] == "0")


def _norm(t):
    if t and t[0] == "0":
        return "5" + t[1]
    if len(t) == 3 and t[2] == "r":
        return t[0] + t[1]
    return t


def yaku_info(hand, calls=0, dora_markers=None, melds=None, seat_wind=None, round_wind=None):
    """手牌的役/打点线索。melds: 我方副露 [{'type','pai','consumed'}]
    seat_wind/round_wind: 自风/场风牌（如 'N'/'E'）。三者与三元牌都算役牌。"""
    ds = dora_set(dora_markers)
    tiles = list(hand)
    for m in (melds or []):
        tiles += list(m.get("consumed") or [])
        if m.get("pai"):
            tiles.append(m["pai"])
    cnt = Counter(_norm(t) for t in tiles)
    # 断幺九
    tan = all((t[0] in "2345678" and t[1] in "mps") for t in cnt)
    # 役牌：三元 + 自风 + 场风
    yaku_set = ["P", "F", "C"]
    for w in (seat_wind, round_wind):
        if w and w not in yaku_set:
            yaku_set.append(w)
    yaku_pairs = [t for t in yaku_set if cnt.get(t, 0) >= 2]
    hon_single = [t for t in yaku_set if cnt.get(t, 0) == 1]
    # 宝牌
    n_dora = sum(cnt[t] for t in ds if t in cnt)
    n_red = sum(v for t, v in cnt.items() if t in ("5m", "5p", "5s")
                and any(_is_red(x) for x in tiles if _norm(x) == t))
    # 对子
    n_pair = sum(1 for t, v in cnt.items() if v >= 2)
    # 平和可能：手牌无刻子
    has_triplet = any(v >= 3 for v in cnt.values())
    return {"tanyao": tan, "yakuhai_pairs": yaku_pairs, "yakuhai_single": hon_single,
            "dora": n_dora, "pairs": n_pair, "has_triplet": has_triplet,
            "dora_tiles": sorted(ds), "counts": cnt}


# ---------------- 安全度 ----------------
def _suji_in(pond, t):
    """t 的「筋」依据：该家自己牌河里出现的、与 t 同筋的牌（n±3 同花色）。
    ⚠ 筋必须看「该家自己」的牌河 —— 别家打了 6筒 推不出 3筒 对这家安全。
    返回命中的牌列表（可能 2 个 → 两筋）。"""
    if t in HON_ZH:
        return []
    n, s = int(t[0]), t[1]
    return [f"{k}{s}" for k in (n - 3, n + 3)
            if 1 <= k <= 9 and f"{k}{s}" in pond]


def safety_grade(tile, pond, visible=None, tile_visible_cnt=0, ponds=None):
    """对某一家（其牌河 = pond）的安全度。返回 (score 越高越安全, 标签)。

    刻度按《统计学麻雀战术》专题二十（第9巡基准，对一家立直）：
      现物 ~0% ＜ 两筋456·筋19·1枚切字牌 ~2% ＜ 生牌客风·筋28·筋37·生牌役牌 ~4~6%
      ＜ 半筋456·无筋19·无筋28·无筋37 ~7~10% ＜ 无筋456 ~13%
    score ≈ 100 − 铳率(%) × 7，便于线性比较（100 = 现物，9 = 无筋中张）。

    ponds: 四家牌河 —— **只用于「壁 / no-chance」这类全场信息**（t±3 已见 4 张 → 挡掉一组两面）；
           筋仍然只看该家自己的牌河（pond）。
    """
    t = _norm(tile)
    if t in pond:
        return 100, "现物(绝对安全)"
    vis = visible or {}
    if t in HON_ZH:
        n = vis.get(t, 0)
        if n >= 3:
            return 98, "绝张字牌"
        if n == 2:
            return 96, "现二字牌"
        if n == 1:
            return 86, "现一字牌"
        return 65, "生牌字牌(准安牌)"
    n, s = int(t[0]), t[1]
    hits = _suji_in(pond, t)
    if hits:
        if n in (1, 9):
            base, lab = 86, "19 筋牌"
        elif n in (4, 5, 6) and len(hits) >= 2:
            base, lab = 86, "两筋456"
        elif n in (2, 8):
            base, lab = 65, "28 筋牌"
        elif n in (3, 7):
            base, lab = 62, "37 筋牌"
        else:
            base, lab = 55, "456 筋牌"
    else:
        if n in (1, 9):
            base, lab = 44, "无筋幺九"
        elif n in (2, 8):
            base, lab = 40, "无筋2·8"
        elif n in (3, 7):
            base, lab = 37, "无筋3·7"
        else:
            base, lab = 9, "无筋中张(4~6)"
    # 壁 / no-chance：t±3 同花色已见 4 张 → 该侧两面被排除
    # （优先用「全场可见」visible；未提供时才退回 ponds，避免同一牌河被重复计入）
    cnt = Counter(vis)
    if not cnt:
        for p in (list(ponds or []) + [pond]):
            cnt.update(p)
    wall = sum(1 for k in (n - 3, n + 3)
               if 1 <= k <= 9 and cnt.get(f"{k}{s}", 0) >= 4)
    if wall:
        base += 10 * wall
        lab += "·%s壁" % ("双" if wall >= 2 else "单")
    return base, lab


def risk_table(tile, riichi_ponds, visible=None):
    """对全部立直家取最危险的一家，返回 (最差score, 标签)。"""
    worst = (101, "无人警戒")
    for p in riichi_ponds:
        r, lab = safety_grade(tile, p, visible, 0)
        if r < worst[0]:
            worst = (r, lab)
    return worst
