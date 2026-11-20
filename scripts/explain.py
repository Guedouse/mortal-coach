# -*- coding: utf-8 -*-
"""为每手恶手写「Mortal 为什么这么打」的解读（只分析 Mortal 的最优解）。

依据 —— 口径一律按 data/theory/_V2_理论口径.md（2026-10-28 版）：
  原文 28 篇（data/theory/*.txt）只作「出处」，不再直接当结论引用。
  · 牌效率（G·ウザク《麻将学习·牌效率》／《何切问答200问》／令和版《现代麻雀技术论》）：
    枚数比较、两面>嵌张>边张、孤张 3~7>2/8>1/9、5 组牌(block)理论、好形率、
    复合形价值、张数优先于变化（4 张边张 > 3 张坎张）、改良（将来性）
  · 押引（《现代麻将技术论·押引理论》＋《铁攻的条件》）：1 巡听牌率 ≈ 有效枚数×5/6、
    好牌先打（序盘/一向听无必要）、留安三前提 —— 但**这些表都以「能弃和」为前提**，
    手里没有 2~3 枚安牌时不可套表（V2 §2 L4）
  · 铳率（《铳率原理》＋《统计学麻雀战术》专题二十，第 9 巡对一家立直）：
    现物 ~0% ＜ 筋19·两筋456 ~2% ＜ 生牌字牌·筋28 4~6% ＜ 半筋456·无筋19/28/37 7~10%
    ＜ 无筋456 ~13%。**绝对值随筛选条件变化，只做排序比较，不当常数用**（V2 §4 M1）
  · 立直（《统计学麻雀战术》专题 2-2/7/10）：先制愚形原则上即立 —— 立直和率约为默听的
    七成、两面立直的七成半，但打点翻倍、被追立仅 ~20%，局收支更高（V2 §1 R1）
  · AI 方法论（V2 §4）：Mortal 是「这一巡最优」不是「全局最优」，没有安牌储备与跨局目标；
    微差（P 差<5pt 或 Q 损<0.3）不算错

【两大类解读，模板不同】
  · 进攻/牌效类 → 必须写明两种切法的进张（种数＋枚数＋具体牌）＋「丢 X 赚 Y」的账
  · 防守类（安全优先/留安）→ 只讲防守逻辑（场况威胁 → 逐家安全度含最坏档 → 原理 → 结论），
    不写进张枚数/向听/搭子形状

【攻守页（战略层，独立一页）】
  牌效页回答「哪张进张多」，安全页回答「哪张最安全」，但都不回答「现在该不该打这张」。
  attack_defense() 用三个量把这件事讲透，每句都带数字：
    · 威胁 threat_lines()：几家立直（亲家/子家）、几副露、副露里有没有宝牌
    · 本钱 own_lines()：打完后的向听、进张枚数（≤ 一向听才算每巡摸到率）、主线役与成型点数
    · 退路 _escape_line()：对最危险的一家，手里还剩几张 ≥86 分的强安牌
  结论分五种说法：不用取舍（又快又安全）/ 继续进攻 / 继续推进（谨慎）/ 继续做牌 / 该守·偏守。
  无人立直且无副露时不出这一页（场况行已交代）。

输出文本按行分成若干「语义块」，供 build_xlsx_kd.py 上色（行首特征识别）：
  【…】  标题      → 深蓝
  场况：…          → 灰
  ①/② …            → 正文（黑）
  原理：…          → 蓝（斜体）
  结论：…          → 红（加粗）
  Mortal 各选择…   → 深绿
  —— 参考…        → 灰
"""
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

BASE = Path(os.environ.get("MC_APP") or Path(__file__).resolve().parent.parent)
LIB = Path(os.environ.get("MC_LIB") or BASE / "library")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mjcalc
import mjeval as E
import yakucalc as YK

P = LIB
SEAT = ["下家", "对家", "上家"]
CALLNAME = {"chi": "吃", "pon": "碰", "kan": "杠", "daiminkan": "大明杠",
            "ankan": "暗杠", "kakan": "加杠"}
YAKUHAI = {"P", "F", "C"}
ALL_TILES = [f"{n}{s}" for s in "mps" for n in range(1, 10)] + list("ESWNPFC")
SAFETY_EDGE = 12          # 防守类判定的安全度差阈值（新刻度下 12 分 ≈ 铳率 1.7pp）


def stage_of(ju):
    return "序盘" if ju <= 6 else ("中盘" if ju <= 12 else "终盘")


def _goal(s):
    """打完牌后处于 s 向听 → 这批「进张」摸到之后到达的状态。
    s=2 → 1 向听；s=1 → 听牌；s=0 → 和牌。"""
    t = s - 1
    return "和牌" if t < 0 else ("听牌" if t == 0 else f"{t} 向听")


def _shanten_zh(s):
    """0 向听 = 听牌，写「0 向听」很别扭。"""
    return "听牌" if s == 0 else f"{s} 向听"


def build_visible(rec, hand=None):
    """场见牌：四家牌河 + 四家副露 + 宝牌指示牌。

    ⚠ 牌河快照里**仍保留着被鸣走的那一张**，它同时被算进 melds，会重复计数
    （实测有牌种被算到 8 张）。因此用「4 − 自己手牌」作上限裁剪。
    """
    c = Counter()
    for p in (rec.get("ponds") or []):
        c.update(p)
    for ml in (rec.get("melds") or []):
        for m in ml:
            for x in (m.get("consumed") or []):
                c[x] += 1
            if m.get("pai"):
                c[m["pai"]] += 1
    for d in (rec.get("dora") or []):
        if d and d != "?":
            c[d] += 1
    if hand:
        hc = Counter(hand)
        for t in list(c):
            cap = max(0, 4 - hc.get(t, 0))
            if c[t] > cap:
                c[t] = cap
    return dict(c)


def _bk_of(rec):
    """由 kyoku 字符串取 (场风 'E'/'S', 局数 1..4)。"""
    k = rec.get("kyoku") or "E1局"
    bk = k[0] if k[0] in "ES" else "E"
    num = 1
    m = re.search(r"[ES](\d)局", k)
    if m:
        num = int(m.group(1))
    return bk, num


def _round_wind(rec):
    return _bk_of(rec)[0]


def _seat_wind(rec, seat=None):
    """自风 = 该局的庄家轮转位置。E2 时庄家已是座次1，所以座次0 的自风是北。"""
    bk, num = _bk_of(rec)
    rnd = 0 if bk == "E" else 1
    dealer = (rnd * 4 + (num - 1)) % 4
    s = rec.get("seat", 0) if seat is None else seat
    return "ESWN"[(s - dealer) % 4]


def _dealer_of(rec):
    """该局庄家的绝对座次。"""
    bk, num = _bk_of(rec)
    rnd = 0 if bk == "E" else 1
    return (rnd * 4 + (num - 1)) % 4


def hand_shape_line(rec):
    """手牌形状一句话：向听 + 面子/对子/搭子/浮牌 + 门前或副露。"""
    hand = list(rec.get("tehai14") or [])
    if not hand:
        return "—"
    calls = rec.get("calls") or 0
    st = E.analyze_struct(hand, calls, cap=99)
    s = mjcalc.shanten(hand, calls)
    seg = ["听牌" if s == 0 else f"{s} 向听"]
    items = []
    if st["melds"]:
        items.append(f"面子 {st['melds']}")
    dak = st["ryanmen"] + st["kanchan"] + st["penchan"] + st["pairs"]
    if dak:
        items.append(f"搭子 {dak}")
    if st["isolated"]:
        items.append(f"浮牌 {st['isolated']}")
    seg.append(" · ".join(items) if items else "整手散牌")
    seg.append("门前" if not calls else f"已副露 {calls} 组")
    return " · ".join(seg)


def _yakuhai_kind(t, rec):
    """役牌的类别：三元牌 / 自风 / 场风 / 连风（自风=场风）。"""
    if t in ("P", "F", "C"):
        return "三元牌"
    sw, rw = _seat_wind(rec), _round_wind(rec)
    if t == sw and t == rw:
        return "连风牌"
    if t == sw:
        return "自风"
    if t == rw:
        return "场风"
    return "役牌"


def analyze_after(rec, tile, vis):
    """打出 tile 之后的手牌：向听、进张、好形率、牌型、打点。"""
    hand = list(rec["tehai14"])
    if tile not in hand:
        return None
    hand.remove(tile)
    calls = rec["calls"]
    # 打出的这张已进牌河，不可能再摸回来 —— 漏这一步会把「刚切的牌」算成还有 4 张
    vis = dict(vis)
    vis[tile] = vis.get(tile, 0) + 1
    s, uk = mjcalc.ukeire(hand, calls, vis)
    st = E.analyze_struct(hand, calls)
    gsr = E.good_shape_rate(hand, calls, vis)
    yk = E.yaku_info(hand, calls, rec.get("dora"), rec.get("fuuro_self"),
                     _seat_wind(rec), _round_wind(rec))
    return {"hand": hand, "shanten": s, "ukeire_kinds": len(uk),
            "ukeire_tiles": sum(uk.values()), "ukeire": uk,
            "struct": st, "good": gsr, "yaku": yk}


def _uk_str(uk, limit=12):
    """进张明细：牌(枚)。

    2026-11-19 起解读正文**不再调用**它：进张牌名由前端牌图展示（`handBlock()` 把全部有效牌
    连枚数一起画出来），文字里再罗列一遍是重复。保留函数供临时排查用。
    """
    items = sorted(uk.items(), key=lambda x: (-x[1], x[0]))
    s = "·".join(f"{E.zh(k)}{v}" for k, v in items[:limit])
    return s + (f"…（共 {len(items)} 种）" if len(items) > limit else "")


def _meld_desc(rel, melds):
    """副露内容描述，如「对家已碰發、白」「上家已吃7索（5索(赤)6索）」。同一家的同类副露合并。"""
    groups, order = {}, []
    for m in melds:
        ty = m.get("type")
        if ty not in groups:
            groups[ty] = []
            order.append(ty)
        groups[ty].append(m)
    parts = []
    for ty in order:
        ms = groups[ty]
        name = CALLNAME.get(ty, ty)
        if ty == "chi":
            for m in ms:
                cons = "".join(E.zh(x) for x in (m.get("consumed") or []))
                parts.append(f"{rel}已吃{T(m.get('pai'))}（{cons}）")
        else:
            pais = "、".join(T(m.get("pai")) for m in ms)
            parts.append(f"{rel}已{name}{pais}")
    return "、".join(parts)


def opponents(rec):
    """在场攻击者：已立直的人 + 有任意副露（≥1 副）的人。带副露内容描述。"""
    out = []
    ri = rec.get("riichi") or [False] * 4
    melds = rec.get("melds") or [[], [], [], []]
    ponds = rec.get("ponds") or [[], [], [], []]
    for o in range(4):
        if o == rec["seat"]:
            continue
        rel = SEAT[(o - rec["seat"]) % 4 - 1]
        if o < len(ri) and ri[o]:
            out.append({"o": o, "rel": rel, "tag": "立直", "pond": ponds[o],
                        "desc": f"{rel}已立直"})
        elif o < len(melds) and melds[o]:
            out.append({"o": o, "rel": rel, "tag": "副露", "pond": ponds[o],
                        "desc": _meld_desc(rel, melds[o])})
    return out


def safety_rows(rec, tile, opps, vis):
    """逐家安全度 → (最坏 (score, lab, opp), [(rel, lab, score), ...])。"""
    ponds = rec.get("ponds") or []
    rows, worst = [], None
    for op in opps:
        sc, lab = E.safety_grade(tile, op["pond"], vis, 0, ponds)
        rows.append((op["rel"], lab, sc))
        if worst is None or sc < worst[0]:
            worst = (sc, lab, op)
    return worst, rows


def _rows_str(rows):
    return "／".join(f"{rel}「{lab}」" for rel, lab, _ in rows)


# ---------------- 攻防判断（战略层：这一手到底该攻还是该守） ----------------
# 为什么单独一层：牌效页回答「哪张进张多」，安全页回答「哪张最安全」，
# 但两者都回答不了「现在该不该打这张牌」——那是「攻 vs 守」的取舍，
# 判据只有三个：对手有多强（威胁）、自己有多少本钱（速度/打点）、还能不能退（安牌）。
def _danger_opp(rec, opps):
    """最需要警惕的一家：亲家立直 ＞ 子家立直 ＞ 副露多的一家。"""
    if not opps:
        return None
    dealer = _dealer_of(rec)
    melds = rec.get("melds") or [[], [], [], []]

    def key(op):
        n = len(melds[op["o"]]) if op["o"] < len(melds) else 0
        return (1 if op["tag"] == "立直" else 0,
                1 if op["o"] == dealer else 0, n)
    return max(opps, key=key)


def _safe_tiles(rec, opp, vis, skip=None):
    """手里还能当安牌用的张（现物 / 筋19 / 两筋456 / 现字牌，≥86 分）。

    opp 可以是单家，也可以是**攻击者列表** —— 防守永远按最凶的那一家算，
    所以传列表时取每张牌对所有攻击者的最低分。
    skip = 即将打出的那一张，不能算进退路。
    """
    hand = list(rec.get("tehai14") or [])
    if skip:
        sn = E._norm(skip)
        for i, t in enumerate(hand):
            if E._norm(t) == sn:
                hand.pop(i)
                break
    ponds = rec.get("ponds") or []
    opps = opp if isinstance(opp, (list, tuple)) else [opp]
    opps = [o for o in opps if o] or [{}]
    out = []
    for t in hand:
        sc = min(E.safety_grade(t, (o or {}).get("pond") or [], vis, 0, ponds)[0]
                 for o in opps)
        if sc >= 86:
            out.append(t)
    return out


def threat_lines(rec, opps):
    """对手侧：谁在攻、攻到什么程度。返回 (等级 0~3, 行列表)。
    0 无人 / 1 单副露 / 2 双副露或子家立直 / 3 亲家立直或两家立直。"""
    if not opps:
        return 0, []
    dealer = _dealer_of(rec)
    ds = E.dora_set(rec.get("dora"))
    melds = rec.get("melds") or [[], [], [], []]
    lv, out, n_ri = 0, [], 0
    for op in opps:
        o, is_dealer = op["o"], op["o"] == _dealer_of(rec)
        if op["tag"] == "立直":
            n_ri += 1
            lv = max(lv, 3 if is_dealer else 2)
            pn = len(op.get("pond") or [])
            s = f"{op['rel']}{'（亲家）' if is_dealer else ''}已立直"
            if pn:
                s += f"、牌河 {pn} 张"
            if is_dealer:
                s += "，亲家立直铳了是子家的 1.5 倍"
            out.append(s)
        else:
            ml = melds[o] if o < len(melds) else []
            nd = sum(1 for m in ml
                     for t in ([m.get("pai")] + list(m.get("consumed") or []))
                     if t and E._norm(t) in ds)
            lv = max(lv, 2 if len(ml) >= 2 else 1)
            d = op["desc"]
            if op["rel"]:
                d = d.replace("、" + op["rel"] + "已", "、")   # 多副露时别把「上家」念两遍
            s = d + f"（共 {len(ml)} 副露）"
            if nd:
                s += f"，其中 {nd} 张是宝牌"
            out.append(s)
    if n_ri >= 2:
        lv = 3
    return lv, out


def own_lines(rec, mor, outline, before=None):
    """自己侧：速度 + 打点，两句。

    before = 打这张之前的向听。拆搭子换进张时向听会退（1 向听打一张变 2 向听），
    只写「2 向听」会和面板上的「手牌：1 向听」打架，所以两个都写出来。
    """
    s, uk = mor["shanten"], mor["ukeire_tiles"]
    tl = rec.get("tiles_left") or 0
    cur = "已听牌" if s == 0 else f"{s} 向听"
    if isinstance(before, int) and before >= 0:
        pre = "已听牌" if before == 0 else f"{before} 向听"
        a = (f"手牌 {pre} → 打这张后 {cur}" if pre != cur else cur) + f"、进张 {uk} 枚"
    else:
        a = cur + f"、进张 {uk} 枚"
    gd = mor.get("good") or {}
    if s == 0 and isinstance(gd, dict) and gd.get("rate") is not None:
        a += f"（好形率 {gd['rate'] * 100:.0f}%）"
    # 只有听牌 / 一向听（进张十几枚）时「每巡摸到率」才有意义；
    # 4 向听动辄 50 多枚，除以残张会算出 98%，纯属唬人，不如不写
    elif tl and s <= 1 and uk <= tl:
        a += f"（残 {tl} 张，每巡约 {uk / tl * 100:.0f}% 摸到）"
    if outline and outline.get("main"):
        b = f"打点走「{outline['main']}」，成型约 {outline['han']} 番 {outline['pt']} 点"
        if outline.get("prog", 0) < 0.72:
            b += "（还只是倾向，要看进张）"
    else:
        b = "还没有成形的役线，打点只能靠立直/宝牌"
    return [a, b]


def _escape_line(rec, opps, vis, skip):
    """退路：手里还剩几张「对所有攻击者都 ≥86 分」的强安牌。"""
    opps = opps if isinstance(opps, (list, tuple)) else [opps]
    opps = [o for o in opps if o]
    if not opps:
        return "全场没有攻击者，不存在退路问题。"
    st = _safe_tiles(rec, opps, vis, skip)
    who = opps[0]["rel"] if len(opps) == 1 else "任何一家"
    if not st:
        return (f"手里没有一张强安牌（对{who}都不是安牌）—— "
                f"打完这张就无路可退，只能一路押到底。")
    show = "、".join(dict.fromkeys(T(t) for t in st))
    n = len(st)
    if n == 1:
        tail = "只够再挡一手，之后就要开始拆搭子了。"
    elif n == 2:
        tail = "够挡两手，退路是真的。"
    else:
        tail = f"够再打 {n} 手安全牌，弃和撑到流局没问题。"
    if len(set(E._norm(t) for t in st)) < n:
        show += " 等"
    return f"打完这张还剩 {n} 张强安牌（{show}）—— {tail}"


def _meld_used_note(rec, opp, tile):
    """对手的副露里已经用过这张牌 → 补充一句「实际比纸面轻」。

    例：上家吃 7筒（6筒8筒），牌河却没有 7筒。按筋的规则它仍算「无筋3·7」，
    但对手是用自己的 6-8 顺子吃的，再要和 7筒 只剩单骑/嵌张，风险明显低于无筋中张。
    """
    if not opp or not tile:
        return ""
    n = E._norm(tile)
    melds = rec.get("melds") or []
    o = opp.get("o")
    if not isinstance(o, int) or o >= len(melds):
        return ""
    for m in melds[o] or []:
        used = [m.get("pai")] + list(m.get("consumed") or [])
        if any(x and E._norm(x) == n for x in used):
            kd = {"chi": "吃", "pon": "碰", "kan": "杠", "daiminkan": "杠",
                  "kakan": "杠", "ankan": "暗杠"}.get(m.get("type") or "", "用")
            return (f"（{opp['rel']}副露里已经{kd}过 {T(tile)}，他再要这张只剩单骑/嵌张，"
                    f"实际风险低于纸面）")
    return ""


def _risk_line(et_tile, sm, danger, rows=None):
    """这一张牌本身的风险 —— 攻的时候必须把代价摆出来，不能只讲收益。

    sm 是「对所有攻击者取最坏」的安全度 (score, label, opp)；叙述必须用**最坏那一家的
    名字**，不能挂到「最需要警惕的一家」头上 —— 否则会出现「对家明明打过这张（现物），
    却被写成对家无筋」这种自相矛盾（2026-11-19 用户报的 bug）。
    """
    if not sm or not danger:
        return ""
    sc, lab = sm[0], sm[1] or ""
    worst = sm[2] if len(sm) > 2 and sm[2] else danger
    who = worst.get("rel") or danger.get("rel") or ""
    # 别的攻击者那侧更安全时补一句，避免读者以为「全场都危险」
    alt = ""
    if rows:
        safe = [f"{rel}那侧是「{l}」" for rel, l, s in rows if s >= 86 and rel != who]
        if safe:
            alt = f"（{'、'.join(safe)}）"
    if sc >= 86:
        return f"{et_tile} 本身是「{lab}」{alt}，这一步没有安全代价。"
    if sc >= 55:
        return f"从{who}的角度看，{et_tile} 是「{lab}」{alt}，属中等风险，但不是最差的一档。"
    return (f"从{who}的角度看，{et_tile} 是「{lab}」{alt}—— 这是本手最大的代价，"
            f"要攻就得认下这一铳的可能。")


def attack_defense(rec, opps, you, mor, tag, vis, outline, sm, sy, rows_m=None, rows_y=None):
    """生成「攻守」页的行（首行「攻守：…」由分页器单独成页）。

    只回答三件事，且必须落到具体数字上：
      ① 对手有多强（几家立直 / 几副露 / 是不是亲家）
      ② 自己有多少本钱（向听、进张、打点）
      ③ 还能不能退（手里还剩几张强安牌）
    sm/sy = 打 Mortal 那张 / 打实战那张的安全度（**对所有攻击者取最坏**）；
    rows_m/rows_y = 逐家的安全度明细，用来给「风险」那句补一句别家那侧的情况。
    返回 [] 表示这一手没有攻防问题（全场无人进攻），不占一页。
    """
    lv, th = threat_lines(rec, opps)
    if lv == 0:
        return []                     # 纯牌效局面：场况行已经说了「无人立直、无副露」

    danger = _danger_opp(rec, opps)
    defend = (tag == "安全优先")
    th_txt = "；".join(th)
    before = rec.get("shanten_before")
    own = own_lines(rec, mor, outline, before)
    exp_t = rec.get("exp_tile")
    n_safe = len(_safe_tiles(rec, opps, vis, exp_t))
    esc = _escape_line(rec, opps, vis, exp_t)
    L = []

    if not defend:
        # —— 有人攻，但 Mortal 仍选进攻牌
        s_m, s_y = mor["shanten"], you["shanten"]
        at_tile = T(rec.get("act_tile")) if rec.get("act_tile") else "实战那张"
        et_tile = T(rec.get("exp_tile")) if rec.get("exp_tile") else "这张"

        # (a) 攻守同向：Mortal 这张又快、又明显更安全 —— 根本没有取舍
        #     必须「明显更安全」（差够 12 分，约 1.7pp 铳率）才算，否则两张都是无筋牌没意义
        if sm and sy and s_m <= s_y and (sm[0] - sy[0]) >= SAFETY_EDGE:
            rel_m = (sm[2] or danger).get("rel") if len(sm) > 2 else danger["rel"]
            L.append(f"攻守：不用取舍 —— {et_tile} 既是这一手里牌效最好的一手"
                     f"（{_shanten_zh(s_m)}、{mor['ukeire_tiles']} 枚），"
                     f"也恰好是对 {rel_m} 更安全的一档（{sm[1]}，对 打{at_tile} 的「{sy[1]}」）；"
                     f"攻和守指向同一张牌。")
            L.append(f"   威胁：{th_txt}。")
            L.append(f"   本钱：{own[0]}；{own[1]}。")
            L.append(f"   所以这一手不存在「该攻还是该守」的纠结：打 {at_tile} 是"
                     f"向听{'一样' if s_y == s_m else '更差'}（{_shanten_zh(s_y)}）"
                     f"而安全度更低，两头都亏。")
            return L

        # (b) 还没成形：这不是押胜负，是继续做牌
        if s_m >= 2:
            if isinstance(before, int) and before <= 1:
                L.append(f"攻守：继续做牌（主动退向听）—— 打 {et_tile} 会把向听从 "
                         f"{_shanten_zh(before)} 退到 {_shanten_zh(s_m)}，"
                         f"换来进张面从 {you['ukeire_tiles']} 枚做宽到 {mor['ukeire_tiles']} 枚；"
                         f"这不是弃和，也不是硬押，是重整牌型。")
            else:
                L.append(f"攻守：继续做牌 —— 对手已经在攻，但自己还在 {s_m} 向听，"
                         f"这一手不是在拼胜负，是把牌型继续做完。")
            L.append(f"   威胁：{th_txt}。")
            L.append(f"   本钱：{own[0]}；{own[1]}。")
            why = (f"现在离听牌还有两三巡，弃和也守不出什么 —— 剩下的巡目会白白让掉；"
                   f"Mortal 只看「这一巡最优」，它不会为了将来提前储备安牌，"
                   f"所以在自己没听牌之前一律按牌效推进。这一步的真实风险是："
                   f"等到必须弃和时，手里可能已经没有安牌了。")
            L.append(f"   为什么不弃和：{why}")
            L.append(f"   退路：{esc}")
            rk = _risk_line(et_tile, sm, danger, rows_m)
            if rk:
                L.append("   这一张的风险：" + rk)
                note = _meld_used_note(rec, (sm[2] if len(sm) > 2 else None) or danger, exp_t)
                if note:
                    L.append("   " + note)
            return L

        # (c) 听牌 / 一向听：真押，说清本钱与退路
        if n_safe >= 2:
            L.append("攻守：继续进攻 —— 对手在攻，但这一手押得起：本钱够，退路也在。")
        else:
            L.append("攻守：继续推进（谨慎）—— 牌还能推，但退路很窄，押的是一手之内的速度。")
        L.append(f"   威胁：{th_txt}。")
        L.append(f"   本钱：{own[0]}；{own[1]}。")
        rk = _risk_line(et_tile, sm, danger, rows_m)
        if rk:
            L.append("   这一张的风险：" + rk)
            note = _meld_used_note(rec, (sm[2] if len(sm) > 2 else None) or danger, exp_t)
            if note:
                L.append("   " + note)
        if lv == 1:
            why = ("场上没有立直宣言，对手都只是单副露 —— 副露不等于听牌，"
                   "听牌率与打点都还没兑现；为这种还没成形的威胁放弃自己的牌，是过度防守。")
        elif n_safe == 0:
            why = ("手里一张强安牌都没有，现在想守也守不住 —— 换一张无筋牌去「守」，"
                   "只是把铳率换个方向，不如把这手牌的价值打出来。")
        elif n_safe == 1:
            why = ("手里只剩 1 张强安牌 —— 退路很窄，但正因为窄，现在弃和也没地方躲；"
                   "不如先把这一手推进完，等摸到新的安牌再决定转不转守。")
        else:
            why = (f"手里还有 {n_safe} 张强安牌，随时可以退 —— "
                   f"押引的做法是「有退路就先押一巡」，不是一见到立直/副露就弃和；"
                   f"等对手真的听牌、或者自己的进张断了，再转守也来得及。")
        if s_m == 1 and mor["ukeire_tiles"] <= 8:
            why += (f"（同时也得承认：进张只有 {mor['ukeire_tiles']} 枚，这手本身很慢，"
                    f"押的是一手之内能摸到的运气。）")
        L.append(f"   为什么不弃和：{why}")
        L.append(f"   退路：{esc}")
        return L

    # —— 守：说清「代价」和「赔率」
    s_m, s_y = mor["shanten"], you["shanten"]
    far = s_m >= 2
    at_tile = T(rec.get("act_tile")) if rec.get("act_tile") else "进攻牌"
    et_tile = T(rec.get("exp_tile")) if rec.get("exp_tile") else "这张"
    d_uk = abs(mor["ukeire_tiles"] - you["ukeire_tiles"])
    uk_txt = ("进张完全一样（都是 %d 枚）" % mor["ukeire_tiles"] if d_uk == 0
              else f"进张 {mor['ukeire_tiles']} 枚 对 {you['ukeire_tiles']} 枚，只差 {d_uk} 枚")
    if sm and sm[0] >= 86 and s_m == s_y and d_uk == 0:
        L.append(f"攻守：这一手该守，但不吃亏 —— {et_tile} 是「{sm[1]}」，"
                 f"向听和进张跟实战那张一模一样（{_shanten_zh(s_m)}、{mor['ukeire_tiles']} 枚），"
                 f"等于白捡一份安全。")
    elif sm and sm[0] >= 86 and lv >= 2:
        L.append(f"攻守：这一手该守 —— {et_tile} 是「{sm[1]}」，可以先把这一手安全地过掉。")
    elif sm and sm[0] >= 86:
        L.append(f"攻守：这一手偏守 —— {et_tile} 是「{sm[1]}」，打它不掉速度也不担风险；"
                 f"对手只是单副露，本来也谈不上什么威胁。")
    elif lv >= 2:
        L.append("攻守：这一手该守 —— 对手已经进入听牌射程，而手里没有现物，"
                 "只能退到次优的那一档。")
    else:
        L.append("攻守：这一手偏守 —— 对手的威胁不大，但自己这手牌也没快到值得为它冒险。")
    L.append(f"   威胁：{th_txt}。")
    L.append(f"   本钱：{own[0]}；{own[1]}。")

    if far:
        lead = (f"对手已经在听牌射程内（{th[0]}），而自己还在 {s_m} 向听"
                if lv >= 2 else
                f"对手的副露还没成型、威胁有限；但自己还在 {s_m} 向听")
        why = (f"{lead}、进张 {mor['ukeire_tiles']} 枚，就算全速推进也要两三巡才听牌 —— "
               f"现在为一张牌吃铳，等于拿确定的损失去换一个本来就追不上的和牌。")
    elif s_y > s_m:
        why = (f"打 {at_tile} 能保住 {_shanten_zh(s_y)}，"
               f"代价是吃下「{sy[1] if sy else '无筋'}」这一档的风险；"
               f"打 {et_tile} 会退到 {_shanten_zh(s_m)}，"
               f"但只退这一手就把整次放铳的可能换掉了 —— 对手已经听牌时，一手向听比一次铳便宜。")
    else:
        why = (f"两边的向听一样（都是 {_shanten_zh(s_m)}），推进速度没有区别；"
               f"{uk_txt}，"
               f"而铳率是「{sy[1] if sy else '无筋'}」对「{sm[1] if sm else '安牌'}」—— "
               f"同样的进度，没有理由选会放铳的那一张。")
    if sm and "生牌字牌" in (sm[1] or "") and lv >= 2:
        why += f"（{et_tile} 只是准安牌，约 4~6%，但在没有现物的情况下这已经是最好的一档。）"
    L.append(f"   为什么不攻：{why}")
    L.append(f"   退路：{esc}")
    return L


def _role_of(rec, t):
    """t 在【最优分解】里的角色（委托 mjeval.role_of）。"""
    return E.role_of(rec["tehai14"], t, rec["calls"])


def _safety_principle(lab):
    """按牌张类别给安全度原理（新刻度标签）。"""
    lab = lab or ""
    if "现物" in lab:
        return "现物受振听规则保证，是唯一 0% 的绝对安全牌。"
    if "中张" in lab:
        return "无筋中张(4~6)是所有牌里铳率最高的一类（约 13%），两面对手全都能荣和。"
    if "筋" in lab and "两筋" in lab:
        return "两筋同时挡掉两组两面，铳率约 2%，与现物只差单骑/坎张/双碰那一档。"
    if "筋" in lab:
        return "筋牌只挡掉一组两面，剩下坎张/单骑/双碰，铳率约为无筋的一半。"
    if "字牌" in lab:
        return ("字牌不参与两面，只能被单骑/双碰/国士荣和，铳率约 4~6%；"
                "但它只是「准安牌」，不是绝对安牌，且巡目越深越危险。")
    if "幺九" in lab:
        return "无筋幺九好形两面基本组不成，铳率约 7~8%，是无筋里最安全的一档。"
    return "安全度排序：现物 ＞ 两筋456/筋19 ＞ 字牌·筋28·筋37 ＞ 无筋19·28·37 ＞ 无筋中张(4~6)。"


def sev_of(qg):
    """期望损失的三档 —— 与 badlevel.js 的 loss 刻度对齐（界面徽章用同一套话术）。

    早期是五档（可忽略/轻微/中等/明显/重大），但界面只认三档，文案里冒出
    「（明显）」这种界面上找不到的词只会让人对不上号。
    """
    return "严重" if qg >= 0.70 else ("中等" if qg >= 0.30 else "轻微")


def bakaze_of(rec):
    k = (rec.get("kyoku") or "")
    return k[0] if k and k[0] in "ESWN" else None


def discard_value(rec, t):
    """这张牌「现在切掉会损失多少价值」——越大越不该切。返回 (分数, 角色)。"""
    hand = rec["tehai14"]
    n = E._norm(t)
    role = _role_of(rec, t)
    base = {"刻子的一部分": 42, "顺子的一部分": 40, "两面搭子的一部分": 32,
            "对子": 26, "嵌张搭子的一部分": 20, "边张搭子的一部分": 13}.get(role)
    if base is None:      # 孤张
        if t in E.HON_ZH:
            sw, rw = _seat_wind(rec), _round_wind(rec)
            if t in ("P", "F", "C"):
                base = 18          # 三元牌
            elif t == sw == rw:
                base = 26          # 连风牌（自风=场风，碰出 2 番）
            elif t in (sw, rw):
                base = 18          # 自风 / 场风
            else:
                base = 8           # 客风（字牌，将来可当安牌）
        else:
            k = int(t[0])
            base = 14 if 3 <= k <= 7 else (10 if k in (2, 8) else 5)
    ds = E.dora_set(rec.get("dora"))
    if n in ds:
        base += 16
    if E._is_red(t):
        base += 20
    return base, role


def dup_score(rec, t):
    """t 的「近似靠张」有多少已经在手里 —— 越高说明这张浮牌越「重复/饱和」。"""
    if t is None or t in E.HON_ZH:
        return 0, 0
    hand = rec["tehai14"]
    c = Counter(hand)
    n, s = int(t[0]), t[1]
    tot = have = 0
    for d in (-2, -1, 1, 2):
        j = n + d
        if 1 <= j <= 9:
            tot += 1
            if c.get(f"{j}{s}", 0) > 0:
                have += 1
    return have, tot


def _ukeire_n(hand, calls, vis):
    """只要进张枚数（比取整张字典略省）。"""
    return sum(mjcalc.ukeire(hand, calls, vis)[1].values())


def improve_info(rec, tile, vis):
    """切掉 tile 后的牌：改良牌（摸到后能降向听 / 把进张放宽的牌）及其剩余枚数。

    做法：先用结构分解**筛候选**（浮牌的 ±1/±2 邻张、嵌张的升级位、役牌字牌自身），
    再对少量候选**精确验证** —— 枚举打牌取最优 (向听, 进张枚数)，
    优于「向听不变且进张更宽」才算改良。避免「12万 摸 1万 也算改良」这类误判。
    返回 (shanten, base_ukeire 枚数, 基础进张dict, 改良dict)。
    """
    hand = list(rec["tehai14"])
    if tile not in hand:
        return None
    hand.remove(tile)
    calls = rec["calls"]
    vis = dict(vis)
    vis[tile] = vis.get(tile, 0) + 1      # 打出的这张已进牌河
    s, uk = mjcalc.ukeire(hand, calls, vis)
    base_n = sum(uk.values())
    st = E.analyze_struct(hand, calls, cap=99)
    in_group = set()
    for _, g in st["groups"]:
        in_group.update(g)

    sw, rw = _seat_wind(rec), _round_wind(rec)
    cands = set()                      # 候选改良牌
    for ti in set(E.t2i(t) for t in hand):
        if ti not in in_group:         # 浮牌 → 邻张
            t = E.i2t(ti)
            if t in E.HON_ZH:
                if t in ("P", "F", "C") or t in (sw, rw):
                    # 役牌字牌：留着有「往刻子/杠子走」的价值；
                    # 注意对子本身不成役，成刻（或杠）才有一番。
                    cands.add(t)
                continue
            n, su = int(t[0]), t[1]
            for d in (-2, -1, 1, 2):
                j = n + d
                if 1 <= j <= 9:
                    cands.add(f"{j}{su}")
    for lab, g in st["groups"]:
        if lab != "嵌张":
            continue
        ts = sorted(E.i2t(x) for x in g)
        n0, su0 = int(ts[0][0]), ts[0][1]
        # 嵌张 (a, a+2)：摸 a-1 → (a-1)a 两面（仅当 a-1 ≥ 2）；
        #                摸 a+3 → (a+2)(a+3) 两面（仅当 a+3 ≤ 9）
        for j in ((n0 - 1) if n0 >= 3 else None, (n0 + 3) if n0 + 3 <= 9 else None):
            if j:
                cands.add(f"{j}{su0}")

    imp = {}
    for u in cands:
        if u in uk:                    # 已是基础进张，不算改良
            continue
        rem = max(0, 4 - vis.get(u, 0) - hand.count(u))
        if not rem or hand.count(u) >= 4:
            continue
        h14 = hand + [u]
        # 先只用 shanten（快）找最优打牌，再对打后的手牌算进张（慢），避免 13 次全算
        best_s, drops = 99, []
        for d in set(h14):
            h = list(h14)
            h.remove(d)
            s2 = mjcalc.shanten(h, calls)
            if s2 < best_s:
                best_s, drops = s2, [h]
            elif s2 == best_s:
                drops.append(h)
        if best_s < s:
            imp[u] = rem
        elif best_s == s and max(_ukeire_n(h, calls, vis) for h in drops) > base_n:
            imp[u] = rem
    return s, base_n, dict(uk), imp


_TILE_MARK = re.compile(r"\{\{([0-9][mps]|[ESWNPFC])\}\}")


def T(t):
    """牌名 → 前端牌图占位。

    正文里凡是要提「哪张牌」，都用 T('2m') 而不是 E.zh('2m')：
    前端 inlineTiles() 会把 {{2m}} 换成真实牌面 SVG，读者不用在「2万」这三个字上费神。
    写进 Excel / 纯文本前，必须先过 strip_tiles()。
    """
    if not t:
        return ""
    if not re.match(r"^(?:[0-9][mps]r?|[ESWNPFC])$", str(t)):
        return str(t)           # 已经是中文/别的串，原样返回，别再套标记
    return "{{%s}}" % t


def strip_tiles(text):
    """把牌图占位还原成中文牌名（Excel、日志等纯文本出口用）。"""
    return _TILE_MARK.sub(lambda m: E.zh(m.group(1)), text or "")


def _tiles_brief(d, limit=8):
    """牌名(枚) 的短列举。

    2026-11-19 起正文不再用它：有效牌与改良牌都由前端牌图展示（`handBlock()` 读
    `hands.*.uk` / `hands.*.imp`），文字里罗列牌名既重复又不直观。保留供临时排查。
    """
    return "·".join(f"{E.zh(k)}{v}" for k, v in
                    sorted(d.items(), key=lambda x: (-x[1], x[0]))[:limit])


def double_pairs(hand):
    """找出「相邻的两组对子」，如 1m1m2m2m → [('1m','2m')]。"""
    c = Counter(hand)
    pairs = [t for t, k in c.items() if k >= 2]
    out = []
    for t in pairs:
        if t in E.HON_ZH:
            continue
        n, s = int(t[0]), t[1]
        for k in (n + 1, n + 2):
            if k <= 9 and c.get(f"{k}{s}", 0) >= 2:
                out.append((t, f"{k}{s}"))
    return out


def _pt_str(o):
    return f"，约 {o['pt']} 点" if o.get("pt") else ""


_YAKU_TILE = re.compile(r"(役牌|客风|场风|自风)\s*([白發中东南西北])")
_HON_TO_CODE = {"白": "P", "發": "F", "中": "C",
                "东": "E", "南": "S", "西": "W", "北": "N"}


def yaku_zh(name):
    """「役牌 白」→「役牌 {{P}}」：役种名里的牌也交给牌图。"""
    return _YAKU_TILE.sub(lambda m: m.group(1) + " " + T(_HON_TO_CODE[m.group(2)]),
                          name or "")


def point_note(pc, et, at):
    """牌效类页面统一补一句「打点」交代。番数没差就返回 None（不占篇幅）。"""
    if not pc or not pc["dh"]:
        return None
    tone = ("Mortal 宁可少这几番，也要先把这一手走完（速度优先）。"
            if pc["dh"] < 0 else "打点上也站得住，不是单纯图快。")
    return (f"   打点：打 {T(et)} 成型 {pc['m']['han']} 番{_pt_str(pc['m'])}，"
            f"打 {T(at)} 是 {pc['y']['han']} 番{_pt_str(pc['y'])}——{tone}")


def point_compare(rec, et, at):
    """两种切法的打点对照：主线役、成型番数、宝牌张数。

    对「打完这张后的 13 张」各跑一次 yakucalc.outline()，所以是可复算的数字，不是印象。
    宝牌 / 断幺 / 役牌 之外，混一色、清一色、一气通贯、三色同顺、一杯口、平和、七对子、
    对对和 都在 routes() 里，能覆盖「为了做特殊役而保打点」的情况。
    返回 None = 手牌对不上（理论上不会）。
    """
    hand = list(rec.get("tehai14") or [])
    melds = rec.get("fuuro_self") or []
    dealer = rec.get("seat") == _dealer_of(rec)

    def one(t):
        h = hand[:]
        try:
            h.remove(t)
        except ValueError:
            return None
        o = YK.outline(h, melds, _seat_wind(rec), _round_wind(rec), rec.get("dora"),
                       dealer, menzen=not melds)
        return {"main": o["main"] or "无役", "names": o["names"] or [],
                "han": o["han"], "pt": o["pt"], "dora": o["dora"],
                "prog": round(o["prog"], 2)}

    m, y = one(et), one(at)
    if not m or not y:
        return None
    # dh > 0 = Mortal 那一手番更高（打实战那张更亏）
    return {"m": m, "y": y, "dh": m["han"] - y["han"], "dpt": m["pt"] - y["pt"]}


def value_reason_m(rec, et, vm, rm, hm, tm, rem_m):
    """只讲「Mortal 切的这张牌为什么最没用」。"""
    ds = E.dora_set(rec.get("dora"))
    if E._norm(et) in ds:
        return (f"{T(et)} 虽然是宝牌，但留着它会挡住整手牌的进张，"
                f"Mortal 选择舍一番换速度。")
    if rm in ("孤张", "孤张字牌"):
        extra = ""
        if tm and hm >= max(2, tm - 2):
            extra = f"而且它的相邻牌已有 {hm}/{tm} 在手上（重复进张），摸进来也难成新面子。"
        elif rem_m <= 2:
            extra = f"而且场上已见 {4 - rem_m} 张、只剩 {rem_m} 枚，成面子机会很少。"
        return f"{T(et)} 是{rm}，切掉它对现有牌型毫无损失。{extra}"
    if tm and hm > tm - 2:
        return (f"{T(et)} 是「重复进张」严重的浮牌：{tm} 种相邻牌里已有 {hm} 种在手上，"
                f"摸进来也难拼成新的面子。")
    if rem_m <= 2:
        return (f"{T(et)} 场上已见 {4 - rem_m} 张、只剩 {rem_m} 枚，"
                f"就算留着也几乎进不了张。")
    return (f"{T(et)} 属于「{rm}」（切牌价值 {vm}）—— 它不是废牌，"
            f"但 Mortal 在这个局面的整体判断里更愿意打它"
            f"（向听 / 待牌 / 打点 / 安全度的综合结果）。")


def cand_label(k):
    if k.startswith("dahai:"):
        return "打" + E.zh(k.split(":", 1)[1])
    if k == "reach":
        return "立直"
    if k == "none":
        return "过"
    if k.startswith("chi:"):
        return "吃" + E.zh(k.split(":", 1)[1])
    if k.startswith("pon:"):
        return "碰" + E.zh(k.split(":", 1)[1])
    return k


def rank_line(rec):
    top = rec.get("top3") or []
    if not top:
        return None
    return "Mortal 评分：" + " ＞ ".join(
        f"{cand_label(k)} {q:+.3f}" for k, _, q in top[:4])


# ---------------- 解读生成 ----------------
def gen(rec):
    seat = rec["seat"]
    vis = build_visible(rec, rec.get("tehai14"))
    ju = rec["junme"]
    stage = stage_of(ju)
    ctx_parts = [f"{rec['kyoku']} 第{ju}巡（{stage}，残{rec['tiles_left']}张）"]

    opps = opponents(rec)
    ri = [o for o in opps if o["tag"] == "立直"]
    fu = [o for o in opps if o["tag"] == "副露"]
    if ri:
        ctx_parts.append("、".join(o["desc"] for o in ri) + "；")
    if fu:
        ctx_parts.append("、".join(o["desc"] for o in fu) + "；")
    if not opps:
        ctx_parts.append("对手没有立直，也没有副露。")

    at, et = rec.get("act_tile"), rec.get("exp_tile")
    ety, aty = rec["expected"].get("type"), rec["actual"].get("type")
    qg = rec["Q_exp"] - rec["Q_act"]

    L = []
    # —— 标题
    if ety == "dahai" and aty in ("dahai", "reach"):
        L.append(f"【为什么打 {T(et)}】")
    elif ety in CALLNAME and aty == "none":
        L.append(f"【为什么建议 {CALLNAME[ety]} {T(rec['expected'].get('pai'))}】")
    elif ety == "none" and aty in CALLNAME:
        L.append(f"【为什么不该 {CALLNAME[aty]}】")
    elif ety == "reach":
        L.append("【为什么这里要立直】")
    else:
        L.append(f"【Mortal 的最优解：{ety} {T(rec['expected'].get('pai'))}】")

    # —— 场况（紧跟标题，放最前）
    L.append("场况：" + "".join(ctx_parts))

    # —— 点数 · 顺位 · 手牌形状 · 做牌方向：这四件决定「该做多大」
    sc_line, rk_line = YK.score_lines(rec.get("scores"), rec.get("seat"),
                                      rec.get("kyoku"))
    if sc_line:
        L.append(sc_line)
    if rk_line:
        L.append(rk_line)
    L.append("手牌：" + hand_shape_line(rec))
    outline = YK.outline(
        rec.get("tehai14") or [], rec.get("fuuro_self"),
        _seat_wind(rec), _round_wind(rec), rec.get("dora"),
        rec.get("seat") == _dealer_of(rec),
        menzen=not (rec.get("fuuro_self") or []))
    # 已经听牌（或已经和了）时牌型就固定了：这时候再写「走 XX 这条线、八成」
    # 属于硬编不是分析——比如 666m 345s 78s 双碰两个副露的听牌手，被写成
    # 「走对对和这条线」，而手里明摆着一组顺子，对对和根本不可能。
    sh_now = mjcalc.shanten(list(rec.get("tehai14") or []), rec.get("calls") or 0)
    if sh_now > 0:
        L.append("做牌：" + outline["text"])

    # ============ 打牌类 ============
    if ety == "dahai" and aty == "dahai" and at and et:
        you = analyze_after(rec, at, vis)
        mor = analyze_after(rec, et, vis)
        if you is None or mor is None:
            L.append("（无法完整重建手牌，跳过细节）")
            return "其他", sev_of(qg), "\n".join(L)

        sm, rows_m = safety_rows(rec, et, opps, vis)
        sy, rows_y = safety_rows(rec, at, opps, vis)
        role_m = _role_of(rec, et)
        tag = "浮牌价值"
        decisive = None
        brief_at = len(L)          # 攻守页插在这里（所有 ① 之前）

        # ---------- ① 退向听换宽进张（进攻类） ----------
        if (you["shanten"] < mor["shanten"]
                and mor["ukeire_tiles"] >= you["ukeire_tiles"] * 1.5
                and mor["ukeire_tiles"] - you["ukeire_tiles"] >= 3):
            tag = "退向听换宽进张"; decisive = "reshuffle"
            L.append(f"① 向听·进张（决定性）：打 {T(et)} 会让向听从 {you['shanten']} 退到 "
                     f"{mor['shanten']}，但进张面大幅做宽 —— 这是主动的「牌型重整」，不是退守。")
            L.append(f"   账：打 {T(et)} 后进张 {mor['ukeire_kinds']} 种 {mor['ukeire_tiles']} 枚，"
                     f"打 {T(at)} 只有 {you['ukeire_kinds']} 种 {you['ukeire_tiles']} 枚"
                     f"（多 {mor['ukeire_tiles'] - you['ukeire_tiles']} 枚）。"
                     f"「一向听」只在进张够宽时才是优势；"
                     f"{you['ukeire_kinds']} 种 {you['ukeire_tiles']} 枚的死一向听，实际比 "
                     f"{mor['ukeire_tiles']} 枚的两向听慢。")
            L.append("原理：《牌效率》——同向听先比有效牌枚数，向听只差一手时"
                     "「进张枚数」才是决定性量；复合形（相邻两组对子等）拆开后能张开更大的进张面。")
            L.append(f"结论：退一手换取 {mor['ukeire_tiles']} 枚进张，打 {T(et)}。")

        # ---------- ② 保住向听（进攻类：必须把两种切法的进张都摆出来，并解释"跨向听不可比"） ----------
        elif mor["shanten"] < you["shanten"]:
            tag = "保住向听"; decisive = "shanten"
            dm, dy = mor["ukeire_tiles"], you["ukeire_tiles"]
            keep_m = "听牌" if mor["shanten"] == 0 else f" {mor['shanten']} 向听"
            L.append(f"① 向听（决定性）：打 {T(et)} 保住{keep_m}，"
                     f"打 {T(at)} 会退到 {_shanten_zh(you['shanten'])} —— 差整整一手。")
            L.append(f"   {T(et)} 是「{role_m}」，切它不会拆掉任何有效搭子。")
            if dy > dm:
                g_m = _goal(mor["shanten"])
                g_y = _goal(you["shanten"])
                pos_m = ("摸到即和牌" if g_m == "和牌"
                         else ("摸到即听牌" if g_m == "听牌" else f"摸到即走到 {g_m}"))
                pos_y = ("和牌" if g_y == "和牌"
                         else ("听牌" if g_y == "听牌" else f"走到 {g_y}"))
                L.append(f"   账：{T(at)} 的进张确实多 {dy - dm} 枚，但这两个数不在同一层 —— "
                         f"打 {T(et)} 那 {dm} 枚是「{pos_m}」的牌，"
                         f"打 {T(at)} 那 {dy} 枚只是「摸到才{pos_y}」的牌，摸到了还得再走一手才追平。"
                         f"所以别拿 {dy} 枚去比 {dm} 枚 —— 跨向听比枚数没有意义。")
                if et in E.HON_ZH:
                    L.append(f"   为什么切字牌反而进张少：打 {T(et)} 不损失任何一块，"
                             f"牌型结构完整，想再降一向听只能让现成的搭子升级，"
                             f"可选牌天然只有 {mor['ukeire_kinds']} 种；"
                             f"打 {T(at)} 是主动拆掉一块，牌型变松，什么牌都能往上补一块 —— "
                             f"{you['ukeire_kinds']} 种里大半只是「补块」，不是「升级」。"
                             f"进张面宽，不等于推进快。")
            else:
                L.append(f"   账：{T(at)} 退一手向听，进张却只有 {dy} 枚（比 {T(et)} 的 {dm} 枚还少）"
                         f"—— 纯亏，连「换宽进张」都没换到。")
            tl = rec.get("tiles_left") or 0
            if tl:
                L.append(f"   折算：{dm} 枚在残 {tl} 张里约 {dm / tl * 100:.0f}%/巡能摸到；"
                         f"退一手等于先把这次机会让掉，之后每一摸都落后一手。")
            L.append("原理：《牌效率》—— 向听优先于枚数：「向听倒退」把和牌往后推一手，"
                     "多一手就是多摸一张牌；枚数优势只在「同一向听内」才可比。"
                     "只有退向听换来的进张宽到足以补回这一手时才划算"
                     "（那种情形归到「退向听换宽进张」，判据是进张至少 1.5 倍且多 3 枚以上）。")
            keep_c = "保住听牌" if mor["shanten"] == 0 else f"保住 {mor['shanten']} 向听不倒退"
            _pn = point_note(point_compare(rec, et, at), et, at)
            if _pn:
                L.append(_pn)
            L.append(f"结论：{keep_c}，{T(et)} 是这一手的最优解。")

        # ---------- ③ 防守类（只讲安全逻辑，不写进张） ----------
        elif opps and sm and sy and (sm[0] - sy[0] >= SAFETY_EDGE):
            tag = "安全优先"; decisive = "safety"
            o = sm[2]
            L.append("① 安全（决定性）：逐个对手核对，取最坏的一家 ——")
            L.append(f"   打 {T(et)} → {_rows_str(rows_m)} → 最坏：{sm[1]}（{sm[0]} 分）")
            L.append(f"   打 {T(at)} → {_rows_str(rows_y)} → 最坏：{sy[1]}（{sy[0]} 分）")
            L.append(f"   {T(et)} 对每一家都不低于「{sm[1]}」，而 {T(at)} 会有一家掉到"
                     f"「{sy[1]}」—— 防守要按最危险的那一家算，只盯一家等于把别家的枪口露出去。")
            L.append(f"原理：《铳率原理》——{_safety_principle(sm[1])}"
                     f"铳率分级（第 9 巡、对一家立直）：现物 ~0% ＜ 筋19·两筋456 ~2% ＜ "
                     f"生牌字牌·筋28 4~6% ＜ 半筋456·无筋19/28/37 7~10% ＜ 无筋456 ~13%；"
                     f"壁只能挡掉一组两面，挡不住嵌张/边张/单骑/双碰。"
                     f"数值随巡目、立直前后（前筋比后筋危险）变化 —— 只用排序，不当常数。")
            extras = []
            if E._norm(et) in E.HON_ZH:
                kind = _yakuhai_kind(E._norm(et), rec)
                is_yak = (E._norm(et) in ("P", "F", "C")
                          or E._norm(et) in (_seat_wind(rec), _round_wind(rec)))
                extras.append(f"   注意：字牌只是「准安牌」（生张约 4~6%），不是绝对安牌"
                              f"（只有现物是 0%）。")
                if is_yak:
                    tgt = ("自己" if E._norm(et) == _seat_wind(rec) else "全场")
                    extras.append(f"   而且 {T(et)} 是{tgt}的{kind} —— 被碰 / 被单骑的风险高于普通客风；"
                                  f"字牌的安全性还会随巡目变差（终盘生张字牌比筋28更危险）。")
            extras.append(f"   最坏的一档来自 {sm[2]['rel']}（{sm[2]['desc']}）；"
                          f"{T(at)} 的危险则集中在 {sy[2]['rel']}（{sy[2]['desc']}）。")
            for e_ in extras:
                L.append(e_)
            L.append(f"结论：{stage}以安全为先，打 {T(et)}。")

        # ---------- ④ 有效进张（进攻类：双侧进张都要写） ----------
        elif (mor["ukeire_tiles"] - you["ukeire_tiles"] >= 3
              or mor["ukeire_kinds"] - you["ukeire_kinds"] >= 2):
            tag = "有效进张"; decisive = "ukeire"
            d = mor["ukeire_tiles"] - you["ukeire_tiles"]
            L.append(f"① 进张（决定性）：{T(et)} 是「{role_m}」，切掉它之后其余搭子的进张变宽。")
            L.append(f"   账：打 {T(et)} 后进张 {mor['ukeire_kinds']} 种 {mor['ukeire_tiles']} 枚，"
                     f"打 {T(at)} 是 {you['ukeire_kinds']} 种 {you['ukeire_tiles']} 枚（净 {d:+d}）"
                     + ("，而且进张牌种也更集中。" if d >= 3 else "。"))
            L.append("原理：《牌效率》——同向听下先比有效牌枚数；两面 4 种 8 枚，嵌张/边张只有 4 枚，"
                     "枚数差距在巡目加深后影响更大。")
            _pn = point_note(point_compare(rec, et, at), et, at)
            if _pn:
                L.append(_pn)
            L.append(f"结论：{T(et)} 的进张面最大（{mor['ukeire_tiles']} 枚），选它。")

        else:
            # ---------- ⑤ 好形率（只在 Mortal 的听牌形**更好**时才算理由） ----------
            gy, gm = you["good"], mor["good"]
            if gy and gm and gm["rate"] - gy["rate"] >= 0.12:
                tag = "听牌质量"; decisive = "good"
                L.append(f"① 听牌质量（决定性）：打 {T(et)} 后摸到有效牌时能做成两面听的比例 "
                         f"{gm['rate']*100:.0f}%（打 {T(at)} 只有 {gy['rate']*100:.0f}%）。")
                L.append("原理：《牌效率》——「两面 > 嵌张 > 边张 > 单骑」，好形听牌的和牌率显著更高，"
                         "进张质量比进张数量更重要。")
                L.append(f"结论：{T(et)} 的最终听牌形最好，选它。")
            else:
                yk_m, yk_y = mor["yaku"], you["yaku"]
                st_m, st_y = mor["struct"], you["struct"]
                # 打点对照：两种切法各自的主线役与成型番数（宝牌/断幺/役牌之外，
                # 混一色、七对子、一气、三色、一杯口等也靠它兜住）
                pc = point_compare(rec, et, at)

                # ---------- ⑥ 打点 · 宝牌 ----------
                if yk_m["dora"] != yk_y["dora"]:
                    tag = "打点·宝牌"; decisive = "dora"
                    ds = E.dora_set(rec.get("dora"))
                    et_dora = E._norm(et) in ds
                    if et_dora:
                        L.append(f"① 打点（决定性）：{T(et)} 虽是宝牌，Mortal 仍选择切它 —— "
                                 f"它判断换来的进张 / 牌型价值高于这一番。")
                        L.append("原理：《牌效率》——宝牌优先留；但当它挡住整手牌的进张时，"
                                 "让位于速度是合理的。")
                        L.append(f"结论：宁可舍一张宝牌也要走最快的路线，打 {T(et)}。")
                    else:
                        kept = [t for t in dict.fromkeys(mor["hand"]) if E._norm(t) in ds]
                        L.append(f"① 打点（决定性）：打 {T(et)} 后手牌保留 {yk_m['dora']} 枚宝牌"
                                 f"（{'、'.join(T(t) for t in kept)}）；"
                                 f"打 {T(at)} 只剩 {yk_y['dora']} 枚。")
                        L.append("   日麻「宝牌 = 一番」，留住它等于白捡一番，不能随手下。")
                        L.append("原理：《牌效率》——处理孤张时把宝牌留到最后再切；"
                                 "巡目越浅、手牌越整齐，越不该为了几枚进张丢掉宝牌。")
                        L.append(f"结论：保住 {yk_m['dora']} 枚宝牌，打 {T(et)}。")

                # ---------- ⑦ 打点 · 断幺 ----------
                elif yk_m["tanyao"] != yk_y["tanyao"]:
                    tag = "打点·断幺"; decisive = "tanyao"
                    if yk_m["tanyao"]:
                        L.append(f"① 打点（决定性）：打 {T(et)} 之后手牌是「全 2~8」，"
                                 f"断幺九成立；打 {T(at)} 会留下幺九 / 字牌，断幺就不成立。")
                        if (mor["shanten"] == you["shanten"]
                                and mor["ukeire_tiles"] == you["ukeire_tiles"]):
                            L.append(f"   两手的向听、进张完全相同（{_shanten_zh(mor['shanten'])} / "
                                     f"{mor['ukeire_kinds']} 种 {mor['ukeire_tiles']} 枚）"
                                     f"—— 保断幺是零代价，等于白捡一番。")
                        if sm and sy:
                            L.append(f"   安全上也不吃亏：{_rows_str(rows_m)} vs {_rows_str(rows_y)}。")
                        L.append("原理：《牌效率》——断幺九只看手里（含副露）有没有 1/9/字牌，"
                                 "与搭子齐不齐无关；那张幺九是必打牌，早打早锁定一番。")
                        L.append(f"结论：保住断幺，打 {T(et)}。")
                    else:
                        L.append(f"① 打点（决定性）：Mortal 主动放弃断幺 —— 它选打 {T(et)}，"
                                 f"用 1 番打点换更宽的进张 / 更好的听牌形。")
                        L.append("原理：《牌效率》——速度优先时「先和牌」大于「多做一番」，"
                                 "巡目偏晚、听牌将成时尤其如此。")
                        L.append(f"结论：舍断幺换速度，打 {T(et)}。")

                # ---------- ⑧ 打点 · 役牌 ----------
                elif set(yk_m["yakuhai_single"]) - set(yk_y["yakuhai_single"]):
                    keep = sorted(set(yk_m["yakuhai_single"]) - set(yk_y["yakuhai_single"]))
                    tag = "打点·役牌"; decisive = "yakuhai"
                    L.append(f"① 打点（决定性）：打 {T(et)} 后手牌保住役牌 "
                             f"{'、'.join(T(x) + '·' + _yakuhai_kind(x, rec) for x in keep)}。")
                    L.append("   「役牌」门清也能用、还能靠碰快速成型，成对 / 碰出即一番，"
                             "是白送的打点。")
                    if (mor["shanten"] == you["shanten"]
                            and mor["ukeire_tiles"] == you["ukeire_tiles"]):
                        L.append(f"   两手向听/进张完全相同（{_shanten_zh(mor['shanten'])} / "
                                 f"{mor['ukeire_tiles']} 枚）—— 留役牌零代价。")
                    L.append("原理：《牌效率》——役牌（三元 / 场风 / 自风 / 连风）的留存优先级高于普通孤张幺九；"
                             "即使暂时只有一张，也值得留着看。")
                    L.append(f"结论：留住役牌 {'、'.join(T(x) for x in keep)}，打 {T(et)}。")

                # ---------- ⑧b 打点 · 其他役种（混一色 / 七对子 / 一气 / 三色 / 一杯口…） ----------
                elif pc and pc["m"]["han"] > pc["y"]["han"]:
                    tag = "打点"; decisive = "point"
                    L.append(f"① 打点（决定性）：打 {T(et)} 留住「{yaku_zh(pc['m']['main'])}」这条线，"
                             f"成型 {pc['m']['han']} 番{_pt_str(pc['m'])}；"
                             f"打 {T(at)} 只剩「{yaku_zh(pc['y']['main'])}」{pc['y']['han']} 番"
                             f"{_pt_str(pc['y'])}。")
                    L.append(f"   差 {pc['dh']} 番。牌效只决定「多快听牌」，打点决定「和了值多少」——"
                             f"这一手不是在比几枚进张，是在比哪条线更值钱。")
                    if (mor["shanten"] == you["shanten"]
                            and mor["ukeire_tiles"] == you["ukeire_tiles"]):
                        L.append("   而且两手的向听、进张完全相同 —— 保打点是零代价，没有理由舍番。")
                    elif mor["ukeire_tiles"] > you["ukeire_tiles"]:
                        L.append(f"   速度上也不吃亏：打 {T(et)} 的进张还多 "
                                 f"{mor['ukeire_tiles'] - you['ukeire_tiles']} 枚。")
                    else:
                        L.append(f"   速度上只慢 {you['ukeire_tiles'] - mor['ukeire_tiles']} 枚进张，"
                                 f"换 {pc['dh']} 番，划算。")
                    L.append("原理：《牌效率》——牌效与打点是两条腿：巡目浅、手牌还没定形时先保打点；"
                             "只有「差一张就听牌」的速度优势才值得舍番。")
                    L.append(f"结论：打 {T(et)}，保住「{yaku_zh(pc['m']['main'])}」。")

                # ---------- ⑨ 牌型（两面更多；或打的是双对子里的那张） ----------
                elif (st_m["ryanmen"] > st_y["ryanmen"]
                      or (st_m["ryanmen"] == st_y["ryanmen"]
                          and any(E._norm(et) in p for p in double_pairs(rec["tehai14"])))):
                    tag = "牌型"; decisive = "shape"
                    L.append(f"① 牌型（决定性）：打 {T(et)} 后保留 {st_m['ryanmen']} 个两面搭子"
                             f"（打 {T(at)} 只有 {st_y['ryanmen']} 个）。")
                    dp = double_pairs(rec["tehai14"])
                    if dp and E._norm(et) in [x for p in dp for x in p]:
                        a, b = dp[0]
                        remain = {t: 4 - vis.get(t, 0) - rec["tehai14"].count(t)
                                  for t in (a, b)}
                        L.append(f"   「{T(a)}{T(a)}{T(b)}{T(b)}」是相邻双对子 —— "
                                 f"拆开来必留一张：{T(a)} 场外还剩 {remain[a]} 枚、"
                                 f"{T(b)} 场外还剩 {remain[b]} 枚。")
                        L.append(f"   拆「剩得少」的那张（{min(remain, key=remain.get)} 的方向），"
                                 f"留下的那张将来还有成对/成刻的机会 —— Mortal 拆的是 {T(et)}。")
                    L.append("原理：《牌效率》——两面搭子进张 4 种 8 枚，嵌张/边张只有 4 枚；"
                             "对子过多时「拆弱留强」，先切价值最低的那一组。")
                    L.append(f"结论：保住 {st_m['ryanmen']} 个两面搭子，打 {T(et)}。")

        # ---------- ⑩ 浮牌价值（牌效打平 → 比浮牌 + 将来性） ----------
        if decisive is None:
            tag = "浮牌价值"
            vm, rm = discard_value(rec, et)
            hm, tm = dup_score(rec, et)
            rem_m = 4 - vis.get(E._norm(et), 0)
            pc = point_compare(rec, et, at)
            im = improve_info(rec, et, vis)
            iy = improve_info(rec, at, vis)
            L.append(f"① 浮牌价值（决定性）：打 {T(et)} —— 它是全手贡献最小的一张"
                     f"（切牌价值 {vm}，越低越先切）。")
            L.append(f"   牌效上与另一手打平（同为 {_shanten_zh(mor['shanten'])}、"
                     f"进张 {mor['ukeire_tiles']} 枚），所以比的是「哪张留着最没用」："
                     f"它是{rm}，靠张重复度 {hm}/{tm}，场上已见 {4 - rem_m} 张、剩 {rem_m} 枚。")
            L.append(f"   → {value_reason_m(rec, et, vm, rm, hm, tm, rem_m)}")
            if im and iy:
                _, bm, uk_m, imp_m = im
                _, by, uk_y, imp_y = iy
                nm, ny = sum(imp_m.values()), sum(imp_y.values())
                # 改良牌也交给牌图展示（前端 hands.*.imp），正文只留数量
                rec["improve"] = {"exp": imp_m, "act": imp_y}
                pm = f"{nm} 枚" if nm else "0 枚（无）"
                py = f"{ny} 枚" if ny else "0 枚（无）"
                L.append(f"② 将来性（改良）：打 {T(et)} 后 → 当前进张 {bm} 枚、"
                         f"另有改良 {pm}；打 {T(at)} 后 → 当前进张 {by} 枚、另有改良 {py}。")
                L.append("   （改良 = 摸到后能降向听、或向听不变但把进张放宽的牌，已扣掉现有进张；"
                         "它只决定「后面能不能升级」，不改变当下的进张。）")
                if nm != ny:
                    more = T(et) if nm > ny else T(at)
                    L.append(f"   → 将来性上打 {more} 后更好（改良 {max(nm, ny)} 枚 vs "
                             f"{min(nm, ny)} 枚），但本手的主判据仍是 ① 里的即时进张 / 打点。")
                else:
                    L.append("   → 两侧将来性相同，这一手的差别不在改良，而在打点或安全。")
            # 打点不构成理由时也要交代一句：让读者知道程序算过番，不是没看
            if pc:
                if pc["dh"] == 0:
                    L.append(f"   打点：两种切法的成型番数相同（{pc['m']['han']} 番"
                             f"{_pt_str(pc['m'])}），这一手的差别不在打点。")
                elif pc["dh"] < 0:
                    L.append(f"   打点：打 {T(at)} 的番反而更高（{pc['y']['han']} 番 vs "
                             f"{pc['m']['han']} 番），Mortal 仍舍番换速度 —— "
                             f"进张多 {mor['ukeire_tiles'] - you['ukeire_tiles']} 枚，先和为先。")
            L.append("原理：《牌效率》——进张数相同时比「浮牌价值」：中张 3~7 > 2/8 > 1/9；"
                     "字牌里役牌 > 客风；宝牌永远最后切。"
                     "中盘后「已见过的」字牌是有效安牌（安牌价值上升）；"
                     "但生张字牌越到终盘越危险，可以高过筋28 —— 别把字牌一律当安牌。")
            L.append(f"结论：{T(et)} 是当前最该先切的一张。")

        # ---------- 攻守（战略层，放最前）：为什么要攻 / 为什么要守 ----------
        brief = attack_defense(rec, opps, you, mor, tag, vis, outline, sm, sy,
                               rows_m, rows_y)
        for k, ln in enumerate(brief):
            L.insert(brief_at + k, ln)

    # ============ 不该立直 ============
    elif ety == "dahai" and aty == "reach":
        tag = "暂不立直"
        t_lv, t_th = threat_lines(rec, opps)
        t_danger = _danger_opp(rec, opps)
        n_safe = len(_safe_tiles(rec, opps, vis, et)) if opps else 0
        pt = (outline or {}).get("pt") or 0
        L.append(f"① 攻守（决定性）：Mortal 认为这一巡应当先打 {T(et)}、暂不立直。")
        if t_th:
            L.append(f"   本手场况：{'；'.join(t_th)}；自己已听牌，"
                     f"手里对最危险的一家只有 {n_safe} 张强安牌。")
        else:
            L.append(f"   本手场况：全场无人立直、也无人副露；自己已听牌，"
                     f"成型约 {pt} 点。" if pt else
                     f"   本手场况：全场无人立直、也无人副露；自己已听牌。")
        if t_th and n_safe <= 2:
            hit = ("「已有人攻击、而自己的安牌不够」—— 立直会把门清锁死，"
                   "之后摸到无筋牌只能硬打，等于先把退路扔掉。")
        elif pt >= 8000:
            hit = (f"「打点已在满贯以上」—— 成型约 {pt} 点，立直只多一番，"
                   f"增幅补不上手牌被锁死的代价。")
        elif len(opps) >= 3:
            hit = ("「立直后的放铳风险高于这一番」—— 场上三家都在副露，"
                   "立直等于把听牌公开、又锁死手牌，之后摸到危险牌只能硬打。")
        elif ju <= 6:
            hit = "「巡目还早、改良面够」—— 现在默听，摸到好牌还能换成更宽的听牌。"
        else:
            hit = ""
        if hit:
            L.append("   这一手踩中：" + hit)
        else:
            L.append("   这一手踩中其中一条 —— 立直那一番的收益，补不上它失去的东西。")
        L.append("   注意：这是「例外」，不是通例。先制听牌默认要立直：愚形立直的和率约为默听的七成"
                 "（5 巡 53% vs 73%、8 巡 43% vs 58%、12 巡 31% vs 40%），但打点翻倍、"
                 "被追立只有 20% 上下 —— 局收支是立直更高。所以「不立直」必须满足下面某一条：")
        L.append("   例外一：改良面 ≥4 种且巡目 ≤6（摸到任意一张就换成明显更好的听牌）；"
                 "例外二：已有人攻击，而自己手里安牌不够，立直等于放弃退路；"
                 "例外三：打点已在满贯以上，立直只增一番、提升效率变差，却照样锁死手牌；"
                 "例外四：立直后的放铳风险高于这一番的收益（如对方明显在狙大牌）。")
        L.append("原理：《统计学麻雀战术》专题 2-2 / 7 —— 立直不使和率腰斩（稳定停在默听七成以上），"
                 "但等改良的代价是硬的：1 巡起手花 8~9 巡才值得让打点翻倍，"
                 "4 种改良牌平均要 8 巡才摸到，所以改良张不到 4 种一律即立。")
        L.append(f"结论：这一巡先打 {T(et)}，不立直 —— 但这是特定条件下的一手，不是「听牌不必立」。")

    # ============ 应当鸣牌 ============
    elif ety in CALLNAME:
        tag = "应当鸣牌"
        p = T(rec["expected"].get("pai"))
        cons = "".join(T(x) for x in (rec["expected"].get("consumed") or []))
        L.append(f"① 速度（决定性）：{CALLNAME[ety]} {p}"
                 + (f"（用 {cons}）" if cons else "") + " 能直接固定一组面子。")
        L.append("   吃 / 碰把「需要自己摸」变成「已经到手」，推进速度明显；"
                 "此处鸣牌不会牺牲重要打点、也不会让防守崩盘。")
        L.append("原理：《牌效率》——「吃是 2 倍速、碰是 4 倍速」，能副露的两面×2 一向听值得鸣。")
        L.append(f"结论：应当 {CALLNAME[ety]} {p}。")

    # ============ 不宜鸣牌 ============
    elif ety == "none" and aty in CALLNAME:
        tag = "不宜鸣牌"
        L.append(f"① 攻守（决定性）：Mortal 认为这里应当过，不要 {CALLNAME[aty]}。")
        L.append("   鸣牌会让手牌变小（失去平和 / 门清立直 / 断幺等打点）、暴露手牌、"
                 "并失去防守弹性；收益抵不过代价。")
        L.append("原理：《押引理论·副露的特征》——副露是攻击形式，本身是常规手段"
                 "（高手与 AI 的副露率都在 25~30%）；此处不鸣，是因为丢掉的打点/防守弹性"
                 "大于换来的速度。")
        L.append("结论：这一巡按兵不动，保持门清。")

    # ============ 应当立直 ============
    elif ety == "reach":
        tag = "应当立直"
        bt = E.best_tenpai(rec["tehai14"], rec["calls"], vis)
        L.append("① 立直（决定性）：手牌已经听牌，Mortal 认为应当立直。")
        if bt:
            cnt, kinds, d, w = bt
            L.append(f"   最优的打法是打 {T(d)}，听 "
                     + "、".join(f"{T(k)}({v[0]}，{v[1]} 枚)" for k, v in w.items())
                     + f"，合计 {cnt} 枚 / {kinds} 种。")
        L.append("   立直能压迫对手、锁定一番、并带来里宝牌机会；此处手牌形与巡目都支持立直。")
        if any(o["tag"] == "立直" for o in opps):
            L.append("   对照：场上已经有人立直，这一手是「追立」—— 不立就只能默听跟在后面，"
                     "立了至少把主动权抢回来，还有机会逼他先弃和。")
        elif opps:
            L.append("   对照：场上只有副露、还没人立直 —— 这是先制立直，"
                     "副露家不能再用两面慢慢推进，只能被动应付你的听牌。")
        else:
            L.append("   对照：全场还没人立直 —— 先制立直没人跟你抢速度，"
                     "一番 + 里宝 + 一发/自摸的机会全是白拿的。")
        L.append("原理：《统计学麻雀战术》专题 2-2 / 7 / 10 —— 先制立直即立："
                 "愚形立直和率仍有默听的约七成、两面立直的约七成半，而打点翻倍"
                 "（立直和了平均 6500 点以上，含里宝/一发/自摸），被追立只有 ~20%；"
                 "两面立直 > 振听三面 > 愚形立直 ≈ 振听两面。")
        L.append("结论：应当立直。")

    else:
        tag = "其他"
        L.append(f"Mortal 的最优解是「{ety}」，与实战选择不同。")

    # —— 收尾：评分与权重（放最后）
    rl = rank_line(rec)
    if rl:
        L.append("")
        L.append(rl)
    L.append("")
    L.append(f"—— 参考：你的权重 {rec['P_act']*100:.1f}%、Mortal {rec['P_exp']*100:.1f}%"
             f"（差 {rec['gap']*100:.0f}pt）；Q 值 {rec['Q_act']:.3f} vs {rec['Q_exp']:.3f}，"
             f"期望损失 {qg:.3f}（{sev_of(qg)}）")
    return tag, sev_of(qg), "\n".join(L)


# ============================ 分步（分页）视图 ============================
# 把上面生成的整段文字，按「一个思考点一页」切开，供面板翻页显示。
# 页序 = 思考顺序：局面 → 牌效/打点/防守/立直/鸣牌（有几页取决于这手实际用到哪些）
#            → 结论 → 候选评分。文字一个字都不改，只重组。

# 小标题里的关键词 → 大类（顺序敏感：先匹配具体，再落到牌效）
STEP_CLASS = (
    ("安全", "防守"),
    ("打点", "打点"), ("役牌", "打点"), ("宝牌", "打点"), ("断幺", "打点"),
    ("立直", "立直"),
    ("鸣牌", "鸣牌"), ("副露", "鸣牌"),
    ("向听", "牌效"), ("进张", "牌效"), ("浮牌", "牌效"),
    ("听牌质量", "牌效"), ("牌型", "牌效"), ("改良", "牌效"),
)

LESSON = {
    "浮牌价值": "孤张先切：1/9 与客风字牌最没用，3~7 别当浮牌切掉。",
    "有效进张": "同向听先比枚数：两面 8 枚 > 嵌张 4 枚，别被「种类多」骗了。",
    "保住向听": "别为了多几枚进张退一手向听，退一手的代价通常更大。",
    "退向听换宽进张": "只有进张翻倍以上才值得退向听，否则守向听。",
    "听牌质量": "宁可晚一手听良形，也别急着听愚形——除非打点或场况需要。",
    "安全优先": "有人立直或副露就逐家算安全度取最坏，现物 > 筋 > 无筋。",
    "打点·役牌": "自风/场风/三元牌的对子优先留，役牌是打点门票。",
    "打点·宝牌": "宝牌别轻易切，除非它挡住牌效或安全。",
    "打点·断幺": "能保断幺时别吃进幺九，白送的一番不要丢。",
    "打点": "先看番数：舍 1 番换速度只在「差一张就听」时划算，否则保打点。",
    "牌型": "两面 > 嵌张 > 边张；两个对子拆场外剩得少的那张。",
    "应当立直": "先制愚形原则上即立：和率约默听七成，但打点翻倍。",
    "暂不立直": "改良张 ≥4 种、或要保听牌形时才默听，否则立。",
    "应当鸣牌": "能推进向听、鸣完仍有役有打点，就鸣。",
    "不宜鸣牌": "鸣了退向听、丢役、把安牌打光，就别鸣。",
    "其他": "把这一手的判断标准记下来，下次同类牌型直接套。",
}


def _step_class(line):
    for k, v in STEP_CLASS:
        if k in line:
            return v
    return "判断"


def lesson_of(tag):
    if not tag:
        return LESSON["其他"]
    if tag in LESSON:
        return LESSON[tag]
    for k, v in LESSON.items():        # 打点·宝牌 之类的复合标签
        if tag.startswith(k):
            return v
    return LESSON["其他"]


def _step_head(s):
    """「① 安全（决定性）：逐个对手核对…」→ ("安全", "决定性")"""
    body = s.lstrip("①②③④⑤⑥⑦⑧⑨")
    for sep in ("：", ":"):
        if sep in body:
            body = body.split(sep)[0]
            break
    badge = ""
    for b in ("决定性", "改良", "决定性因素"):
        if f"（{b}）" in body or f"({b})" in body:
            badge = "决定性" if b == "决定性因素" else b
            body = body.replace(f"（{b}）", "").replace(f"({b})", "")
    return body.strip(), badge


def steps_of(text, tag="", img=""):
    """把整段解读切成页：[{k, t, b}]，b 为该页正文（多行文本）。

    · 第一页永远是「局面」（场况）
    · 每个 ①②③ 各自成页，标题用「大类 · 小标题」
    · 「原理」并入它上面那一页（论据跟着判断走）
    · 「结论」独立成页，并附一句「下次」
    · 「Mortal 各选择 / —— 参考」合成最后一页「候选评分」
    """
    lines = [l.rstrip() for l in (text or "").split("\n")]
    steps = []
    cur = None

    def push(k, t, line=None):
        nonlocal cur
        cur = {"k": k, "t": t, "b": ([line] if line else [])}
        steps.append(cur)
        return cur

    for ln in lines:
        s = ln.strip()
        if not s:
            if cur:
                cur["b"].append("")
            continue
        if s.startswith("【") and s.endswith("】"):
            continue                      # 标题由面板头部显示
        if s.startswith("场况："):
            push("state", "局面", ln)
            continue
        if s.startswith("攻守："):
            body = s.split("：", 1)[1].strip() if "：" in s else s
            is_def = "守" in body[:8]          # 「这一手该守」/「这一手偏守」
            cur = push("choice", "攻防 · " + ("该守" if is_def else "继续攻"), ln)
            cur["side"] = "守" if is_def else "攻"
            continue
        if s[0] in "①②③④⑤⑥⑦⑧⑨":
            cls = _step_class(s)
            head, badge = _step_head(s)
            title = cls if (not head or head == cls) else f"{cls} · {head}"
            st = push(cls, title, ln)
            if badge:
                st["badge"] = badge
            st["side"] = "守" if cls == "防守" else ("攻" if cls in ("牌效", "打点") else "判")
            continue
        if s.startswith("原理"):
            if cur:
                cur["b"].append(ln)
            else:
                push("theory", "理论依据", ln)
            continue
        if s.startswith("结论"):
            push("concl", "结论", ln)
            continue
        if s.startswith("Mortal 评分"):
            if cur and cur["k"] == "cand":
                cur["b"].append(ln)
            else:
                push("cand", "候选评分", ln)
            continue
        if s.startswith("—— 参考"):
            if cur and cur["k"] == "cand":
                cur["b"].append(ln)
            else:
                push("cand", "候选评分", ln)
            continue
        if cur:
            cur["b"].append(ln)

    # 结论页补一句「下次」
    les = lesson_of(tag)
    for st in steps:
        if st["k"] == "concl":
            st["b"].append(f"下次：{les}")
            break
    else:
        steps.append({"k": "concl", "t": "结论", "b": [f"下次：{les}"]})

    # 去掉空页、压掉连续空行
    out = []
    for st in steps:
        b = [x for x in st["b"]]
        while b and not b[-1]:
            b.pop()
        if not b:
            continue
        st["b"] = "\n".join(b)
        st.setdefault("side", {"state": "局", "concl": "结", "cand": "评"}.get(st["k"], ""))
        out.append(st)

    # 局面页末尾给一句「往下看什么」，相当于这一手的目录
    for i, st in enumerate(out):
        if st["k"] == "state":
            if i + 1 < len(out):
                st["b"] += f"\n往下看：{out[i + 1]['t']}"
            break
    return out


if __name__ == "__main__":
    recs = json.load(open(P / "data" / "bad_moves.json", encoding="utf-8"))
    tags, sevs = Counter(), Counter()
    n = 0
    for r in recs:
        tag, sev, txt = gen(r)
        r["tag"] = tag
        r["severity"] = sev
        r["explain"] = txt
        tags[tag] += 1
        sevs[sev] += 1
        n += 1
        if n % 20 == 0:
            print(f"  ...{n}/{len(recs)}")
    json.dump(recs, open(P / "data" / "bad_moves.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("标签分布:", dict(tags))
    print("严重度分布:", dict(sevs))
