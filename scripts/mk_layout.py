# -*- coding: utf-8 -*-
"""为每条恶手画一张「两种切法对照」图，供 build_xlsx_kd.py 插到 Excel 的「牌型分解」列。

按**恶手成因**分视图（用户 2026-10-14 要求）：
  · 牌效类（浮牌价值 / 有效进张 / 保住向听 / 退向听换宽进张 / 听牌质量）—— 成因就是牌效率，
    **只给牌效率的数据对比**（向听 · 好形率 · 进张 · 改良），**不解读牌型**（牌列不标搭子分组）；
  · 其他情况按各自维度分析：
    安全优先 → 逐家安全度；打点·* → 宝牌/役牌/断幺；牌型 → 两面/嵌张/对子/浮牌统计；
    立直·鸣牌类 → 向听与进张（保留分组）。

进张 / 改良的显示：**牌名按花色上色，枚数用灰色小字并带「枚」字**，两者一眼可辨。

顶部信息行 + 块①（红，Mortal）/ 块②（蓝，实战）+ 底部「决定性因素」与 Mortal 候选评分。
图片路径回写到 bad_moves.json 的 img_layout 字段。
"""
import json
import sys
import os
from collections import Counter
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

BASE = Path(os.environ.get("MC_APP") or Path(__file__).resolve().parent.parent)
LIB = Path(os.environ.get("MC_LIB") or BASE / "library")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mjcalc
import mjeval as E
import explain as X

P = BASE
# 注意：这里**不建目录**。导入本模块时不该产生任何写入（独立 CLI 还没拿到库锁），
# 真正要落图时由调用方建（pipeline_one 自己 mkdir，__main__ 在过闸之后建）。
OUT = LIB / "img_layout"

W, H = 600, 334
TW, TH, GAP, GGAP = 28, 36, 3, 9
BLOCK_H = 132
PAD = 8
RED, BLUE = "#C00000", "#2E75B6"
TINT_R, TINT_B = "#FFF4F4", "#F2F7FD"
LINE, GRAY, DARK, BODY = "#D3D1C7", "#7F7F7F", "#1A1A1A", "#4A4A47"
NUM = "#9A9A9A"
ORDER = {"顺子": 0, "刻子": 1, "对子": 2, "两面": 3, "嵌张": 4, "边张": 5}

# 牌效类（成因即牌效率 → 不解读牌型）
EFF_TAGS = {"浮牌价值", "有效进张", "保住向听", "退向听换宽进张", "听牌质量"}

_F = {}

# 字体查找顺序：随包的 Noto Sans SC（OFL，任何 Windows 都能用）→ 系统中文 → 系统日文。
# 英文版 Windows 只装日文字体（Yu Gothic / MS Gothic），汉字能画、中文专有字会变方框，
# 所以随包字体排第一位，别指望系统。
FONT_BUNDLED = P / "assets" / "fonts" / "NotoSansSC-Regular.otf"
FONT_SYS = (
    r"C:\Windows\Fonts\msyh.ttc",          # 微软雅黑（中文 Windows）
    r"C:\Windows\Fonts\simhei.ttf",        # 黑体
    r"C:\Windows\Fonts\Deng.ttf",          # 等线
    r"C:\Windows\Fonts\simsun.ttc",        # 宋体
    r"C:\Windows\Fonts\YuGothR.ttc",       # 游ゴシック（英文版 Windows 也有）
    r"C:\Windows\Fonts\msgothic.ttc",      # MS Gothic
)


def font(sz, bold=False):
    key = (sz, bold)
    if key in _F:
        return _F[key]
    cands = []
    if FONT_BUNDLED.exists():
        cands.append(str(FONT_BUNDLED))
    if bold:                                # 随包只有 Regular：粗体用同款代替
        cands.insert(1, r"C:\Windows\Fonts\msyhbd.ttc")
    cands.extend(FONT_SYS)
    for p in cands:
        if not Path(p).exists():
            continue
        for idx in ((0, 1) if p.lower().endswith(".ttc") else (0,)):
            try:
                _F[key] = ImageFont.truetype(p, sz, index=idx)
                return _F[key]
            except Exception:
                continue
    print(f"[warn] 没找到可用中文字体，图上文字会显示为方框：{FONT_BUNDLED}", file=sys.stderr)
    _F[key] = ImageFont.load_default()
    return _F[key]


ZH_S = {"m": "万", "p": "筒", "s": "索"}
HON = {"E": "東", "S": "南", "W": "西", "N": "北", "P": "白", "F": "發", "C": "中"}
CALLNAME = {"chi": "吃", "pon": "碰", "kan": "杠", "daiminkan": "大明杠",
            "kakan": "加杠", "ankan": "暗杠"}


def tt(t):
    if not t:
        return ""
    t = E._norm(t)
    if t in HON:
        return HON[t]
    return t[0] + ZH_S.get(t[1], t[1])


def tcolor(t):
    t = E._norm(t) if t else ""
    if t and t[-1] == "m":
        return "#1A1A1A"
    if t and t[-1] == "p":
        return "#185FA5"
    if t and t[-1] == "s":
        return "#1D9E75"
    if t == "P":
        return "#9A9A9A"
    return "#1A1A1A"


def fit(d, s, f, maxw):
    """文字超宽则截断加省略号，保证不越出画布。"""
    if not s or d.textlength(s, font=f) <= maxw:
        return s
    while s and d.textlength(s + "…", font=f) > maxw:
        s = s[:-1]
    return s + "…"


def draw_tile(d, x, y, t, border=LINE, bw=1, fill="#FAFAF7"):
    d.rounded_rectangle([x, y, x + TW, y + TH], radius=4, fill=fill,
                        outline=border, width=bw)
    d.text((x + TW / 2, y + TH / 2 + 1), tt(t), font=font(11), fill=tcolor(t), anchor="mm")


def draw_tile_list(d, x, y, items, sep="·", maxw=None, fs=10, ns=9):
    """分色画「牌名 + 枚数」：牌名用花色色，枚数用灰色小字并带「枚」字。"""
    fz, fn = font(fs), font(ns)
    for i, (t, n) in enumerate(items):
        if i:
            d.text((x, y + 1), sep, font=fn, fill="#C8C8C8")
            x += d.textlength(sep, font=fn) + 3
        s1 = E.zh(t)
        d.text((x, y), s1, font=fz, fill=tcolor(t))
        x += d.textlength(s1, font=fz)
        s2 = f"{n}枚"
        d.text((x, y + 2), s2, font=fn, fill=NUM)
        x += d.textlength(s2, font=fn)
        if maxw and x > maxw:
            d.text((x, y + 1), "…", font=fn, fill="#C8C8C8")
            break
    return x


def split_groups(hand13, calls):
    """按最优分解把牌分成 [(类别, [牌]), ...]，剩下的归入「浮牌」。"""
    st = E.analyze_struct(hand13, calls, cap=99)
    pool = Counter(E.t2i(t) for t in hand13)
    seq = []
    for lab, g in sorted(st["groups"], key=lambda z: ORDER.get(z[0], 9)):
        ts = []
        for x in g:
            if pool.get(x, 0) > 0:
                pool[x] -= 1
                ts.append(E.i2t(x))
        if ts:
            seq.append((lab, ts))
    rest = []
    for x in sorted(pool):
        rest += [E.i2t(x)] * pool[x]
    if rest:
        seq.append(("浮牌", rest))
    return seq


def draw_groups(d, x, y, seq):
    """画分组牌列；连续相同的组只显示一个标签（标 ×n）。返回结束 x。"""
    units, i = [], 0
    while i < len(seq):
        lab, ts = seq[i]
        rep = 1
        while i + rep < len(seq) and seq[i + rep] == (lab, ts):
            rep += 1
        i += rep
        x0 = x
        for r in range(rep):
            for t in ts:
                draw_tile(d, x, y, t)
                x += TW + GAP
            if r < rep - 1:
                x += GGAP - GAP
        x -= GAP
        units.append((x0, x, f"{lab} ×{rep}" if rep > 1 else lab))
        x += GGAP
    for x0, x1, lab in units:
        d.text(((x0 + x1) / 2, y + TH + 5), lab, font=font(9), fill=GRAY, anchor="ma")
    return x


def tiles_sorted(dd):
    return sorted(dd.items(), key=lambda x: (-x[1], E.t2i(x[0])))


def side_stats(rec, tile, vis):
    """某一侧切法的分析数据（按恶手成因定制）。"""
    hand = list(rec["tehai14"])
    if tile not in hand:
        return None
    hand.remove(tile)
    calls = rec["calls"]
    tag = rec.get("tag") or ""
    out = {"hand": hand, "tag": tag}

    if tag == "安全优先":
        kind = "safe"
    elif tag.startswith("打点"):
        kind = "point"
    elif tag == "牌型":
        kind = "shape"
    elif tag in EFF_TAGS:
        kind = "eff"
    else:
        kind = "act"

    out["kind"] = kind
    # 牌效类不解读牌型 → 牌列不标分组；其余保留分组
    out["groups"] = None if kind == "eff" else split_groups(hand, calls)

    if kind == "eff":
        s, base_n, uk, imp = X.improve_info(rec, tile, vis)
        gsr = E.good_shape_rate(hand, calls, vis)
        l1 = "已听牌" if s == 0 else f"{s} 向听"
        if gsr:
            l1 += f" · 好形率 {gsr['rate']*100:.0f}%"
        rows = [
            ("t", l1),
            ("tiles", f"进张 {base_n} 枚 / {len(uk)} 种",
             tiles_sorted(uk)[:7], RED),
            ("tiles", f"另有改良 {sum(imp.values())} 枚",
             tiles_sorted(imp)[:6] if imp else [], GRAY, "无"),
        ]
        out["rows"] = rows
        return out

    if kind == "safe":
        opps = X.opponents(rec)
        if not opps:
            out["rows"] = [("t", "本手无警戒对象")]
            return out
        worst, rws = X.safety_rows(rec, tile, opps, vis)
        avg = sum(r[2] for r in rws) / len(rws)
        out["rows"] = [
            ("t", f"对 {len(rws)} 家：最坏「{worst[1]}」({worst[0]} 分) · 平均 {avg:.0f} 分"),
            ("t", "逐家：" + "／".join(f"{rel}「{lab}」{sc}" for rel, lab, sc in rws)),
        ]
        return out

    if kind == "point":
        yk = E.yaku_info(hand, calls, rec.get("dora"), rec.get("fuuro_self"),
                         X._seat_wind(rec), X._round_wind(rec))
        parts = [f"宝牌 {yk['dora']} 张"]
        if yk["yakuhai_pairs"]:
            parts.append("役牌对子 " + "、".join(E.zh(t) for t in yk["yakuhai_pairs"]))
        if yk["yakuhai_single"]:
            parts.append("役牌单张 " + "、".join(E.zh(t) for t in yk["yakuhai_single"]))
        parts.append("断幺 " + ("成立" if yk["tanyao"] else "不成立"))
        s = mjcalc.shanten(hand, calls)
        out["rows"] = [
            ("t", f"{s} 向听 · " + " · ".join(parts)),
        ]
        return out

    if kind == "shape":
        st = E.analyze_struct(hand, calls, cap=99)
        out["rows"] = [
            ("t", f"两面 {st['ryanmen']} · 嵌张 {st['kanchan']} · 边张 {st['penchan']}"
                  f" · 对子 {st['pairs']} · 浮牌 {st['isolated']}"),
        ]
        return out

    # 立直 / 鸣牌类：给向听与进张
    s, base_n, uk, imp = X.improve_info(rec, tile, vis)
    out["rows"] = [
        ("t", ("已听牌" if s == 0 else f"{s} 向听")),
        ("tiles", f"进张 {base_n} 枚 / {len(uk)} 种", tiles_sorted(uk)[:7], BODY),
    ]
    return out


def draw_case(d, by, idx, label, color, tile, stat, qval, verb="打"):
    """一个切法块：标题+Q · 分析行 · 牌行（切牌 → 留下的牌）。"""
    qf = font(10)
    qt = f"Mortal Q {qval:.3f}" if idx == "①" else f"实战 Q {qval:.3f}"
    qw = d.textlength(qt, font=qf)
    d.text((W - PAD, by + 3), qt, font=qf, fill=color, anchor="ra")
    head = f"{idx} {label} {verb} {tt(tile)}"
    d.text((PAD, by), fit(d, head, font(13, True), W - 2 * PAD - qw - 10),
           font=font(13, True), fill=color)

    yy = by + 22
    for r in stat["rows"]:
        if r[0] == "t":
            d.text((PAD, yy), fit(d, r[1], font(10), W - 2 * PAD), font=font(10), fill=BODY)
        else:                                   # ("tiles", label, items, color[, empty])
            _, lab, items, col = r[0], r[1], r[2], r[3]
            empty = r[4] if len(r) > 4 else "—"
            xx = PAD
            d.text((xx, yy), lab, font=font(10, True), fill=col)
            xx += d.textlength(lab, font=font(10, True)) + 10
            if items:
                draw_tile_list(d, xx, yy, items, maxw=W - PAD)
            else:
                d.text((xx, yy + 1), empty, font=font(9), fill=NUM)
        yy += 16

    py = by + 22 + 16 * 3 + 4        # 固定留 3 行文字位，各类别块内垂直对齐
    tint = TINT_R if color == RED else TINT_B
    x = PAD
    draw_tile(d, x, py, tile, border=color, bw=2, fill=tint)
    d.text((x + TW / 2, py + TH + 5), "切", font=font(9), fill=color, anchor="ma")
    x += TW + 5
    d.text((x, py + TH / 2), "→", font=font(15), fill="#B0AEA5", anchor="lm")
    x += 19
    if stat["groups"]:
        draw_groups(d, x, py, stat["groups"])
    else:
        # 牌效类：不解读牌型 —— 只按序摊开留下的牌，不标搭子分组
        for t in sorted(stat["hand"], key=E.t2i):
            draw_tile(d, x, py, t)
            x += TW + GAP


def build(rec, path):
    et, at = rec.get("exp_tile"), rec.get("act_tile")
    vis = X.build_visible(rec)
    te = (rec.get("expected") or {}).get("type")
    ta = (rec.get("actual") or {}).get("type")
    V = {"dahai": "打", "reach": "立直打", "chi": "吃", "pon": "碰",
         "kan": "杠", "daiminkan": "大明杠", "kakan": "加杠", "ankan": "暗杠"}
    ve, va = V.get(te, te or "?"), V.get(ta, ta or "?")

    img = Image.new("RGB", (W, H), "#FFFFFF")
    d = ImageDraw.Draw(img)

    drawn = rec.get("drawn")
    head = f"{rec.get('kyoku','')} · 第 {rec.get('junme','?')} 巡"
    if drawn:
        head += f" · 摸到 {tt(drawn)}"
    d.text((PAD, 5), fit(d, head, font(10), W - 2 * PAD), font=font(10), fill=GRAY)

    y = 20
    sm, sa = side_stats(rec, et, vis), side_stats(rec, at, vis)
    qe, qa = rec.get("Q_exp"), rec.get("Q_act")

    if et and at and et == at:
        d.text((PAD, y), f"两侧切牌相同（{tt(et)}）", font=font(12, True), fill=DARK)
        if sm:
            draw_case(d, y + 6, "①", "", BLUE, et, sm, qa if qa is not None else 0)
        yb = y + BLOCK_H + 6
    else:
        if et and sm:
            draw_case(d, y, "①", "Mortal", RED, et, sm, qe if qe is not None else 0, ve)
        if at and sa:
            draw_case(d, y + BLOCK_H, "②", "你实战", BLUE, at, sa,
                      qa if qa is not None else 0, va)
        yb = y + BLOCK_H * 2 + 4

    d.line([(PAD, yb), (W - PAD, yb)], fill="#E8E5DC", width=1)
    tag, sev = rec.get("tag", ""), rec.get("severity", "")
    if tag == "保住向听" and rec.get("yours") and rec.get("mortals"):
        _y, _m = rec["yours"], rec["mortals"]
        # 保住向听是「向听 vs 枚数」的取舍：把两边数字并排摆出来，并点明跨向听不可比，
        # 否则 9 枚 vs 51 枚 看着像"打反了"。
        tagline = (f"决定性因素：保住向听（{sev}）　"
                   f"{_m['shanten']} 向听 {_m['ukeire_tiles']} 枚 vs "
                   f"{_y['shanten']} 向听 {_y['ukeire_tiles']} 枚 · 跨向听枚数不可比")
    else:
        tagline = f"决定性因素：{tag}　（严重度：{sev}）"
    d.text((PAD, yb + 6), fit(d, tagline, font(12, True), W - 2 * PAD),
           font=font(12, True), fill=DARK)
    try:
        rl = X.rank_line(rec)
    except Exception:
        rl = ""
    if rl:
        d.text((PAD, yb + 27), fit(d, rl, font(10), W - 2 * PAD), font=font(10), fill=GRAY)
    img.save(path)


if __name__ == "__main__":
    """独立命令行入口：把库里现有的恶手重画一遍对照图，并把图片路径写回 bad_moves.json。

    正常流水线走的是 `build()`（被 pipeline_one 调用，库锁由上游持有），**不经过这里**。
    这里支持的是维护者手工局部刷新：
        python scripts/mk_layout.py                 # 全部重画
        python scripts/mk_layout.py --only-game 261024
        python scripts/mk_layout.py --only-tag 保住向听
        python scripts/mk_layout.py --library D:\\mine\\library

    以前这段直接读写 `BASE/data/bad_moves.json`（牌谱库搬到 LIB 之后就废弃了），
    既跑不通，也不拿库锁 —— 第四轮审计 P2。现在统一走 paths 的库解析 + 写闸。
    """
    import paths as PATHS

    args = sys.argv[1:]
    only = None
    only_game = None
    if "--only-tag" in args:
        only = args[args.index("--only-tag") + 1]
    if "--only-game" in args:
        only_game = args[args.index("--only-game") + 1]

    lib_arg = PATHS.parse_library_arg(args)
    print(PATHS.describe(lib_arg))
    _root, _lib = PATHS.apply(lib_arg)
    LIB = Path(_lib)                 # 模块级变量就地改写，后面只用这一个库
    OUT = LIB / "img_layout"

    # 写库前统一过闸：别的窗口正持锁就零写入退出 3，别把人家正在写的库搅乱
    ok, handle, msg = PATHS.guard_writable(LIB, "重画牌型对照图")
    if not ok:
        print(msg, file=sys.stderr)
        sys.exit(3)
    _LOCK = handle                  # 句柄要一直持有，进程结束由系统释放

    bad = LIB / "bad_moves.json"
    if not bad.exists():
        print(f"!! 找不到 {bad}\n   这个库还没跑过分析（或路径不对）。"
              f"正常分析会在库里生成 bad_moves.json；空库没有图可画。", file=sys.stderr)
        sys.exit(1)
    try:
        recs = json.loads(bad.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"!! 读不了 {bad}：{type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(recs, list) or not recs:
        print(f"!! {bad} 里没有恶手记录（{type(recs).__name__}），没有要画图的。", file=sys.stderr)
        sys.exit(1)

    OUT.mkdir(parents=True, exist_ok=True)
    # 同一 (游戏, 事件号) 可能出现多条（立直回合的两次判定）→ 加序号，避免互相覆盖
    grp = Counter((r["game"], r["i"]) for r in recs)
    ordn = {}
    n = 0
    for r in recs:
        base = f"{r['game']}_{r['i']:04d}"
        if grp[(r["game"], r["i"])] > 1:
            ordn[base] = ordn.get(base, 0) + 1
            name = f"{base}_{ordn[base]}.png"
        else:
            name = f"{base}.png"
        p = OUT / name
        r["img_layout"] = str(p)
        if only and r.get("tag") != only:
            continue
        if only_game and r.get("game") != only_game:
            continue
        build(r, p)
        n += 1
        if n % 40 == 0:
            print(f"  ...{n}")
    # 原子写回：中途崩了也不会留半截 JSON 把整库恶手记录弄坏
    tmp = bad.with_name("bad_moves.json.tmp")
    tmp.write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(bad)
    print(f"已生成牌型对照图 {n} 张 → {OUT}")
