# -*- coding: utf-8 -*-
"""从 Mortal 报告里的 mjai 事件流算「这局打完时被复盘者的名次」。

单独成模块（不 import mjcalc / explain），这样 mk_coach.py 与单测都能直接用。
"""


def place_order(scores, oya=0):
    """按日麻规则排序：点数高者在前，同点按起家顺序（东南西北）。

    oya 是首局庄家座位，也就是起家。返回 [座位, …] 从第 1 名到第 4 名。
    """
    n = len(scores)
    return sorted(range(n), key=lambda i: (-scores[i], (i - oya) % n))


def final_place(report):
    """返回 (place, score)：被复盘者的最终名次与点数；算不出来给 (None, None)。

    只累加 mjai 事件里的分数，不猜：
      - `start_kyoku.scores` 是每局的起始点数（最权威，已含前面所有局的结算）；
      - `reach_accepted` 要先扣 1000 —— 立直棒不在 hora/ryukyoku 的 deltas 里，
        不扣的话和牌 deltas 里回收的供托会让总分凭空多出 1000/2000 点，顺位可能排错；
      - `hora` / `ryukyoku` 的 deltas 才是真正的点数移动。
    流局后供托留在桌上，所以总分**不保证**等于 100000（四麻），这是对的。
    """
    log = report.get("mjai_log") or []
    scores = None
    oya = 0
    first_kyoku = True
    for e in log:
        t = e.get("type")
        if t == "start_kyoku":
            sc = e.get("scores")
            if isinstance(sc, list) and len(sc) in (3, 4):
                scores = [int(x) for x in sc]
            if first_kyoku:
                if isinstance(e.get("oya"), int):
                    oya = e["oya"]          # 首局庄家 = 起家
                first_kyoku = False
        elif t == "reach_accepted":
            a = e.get("actor")
            if scores is not None and isinstance(a, int) and 0 <= a < len(scores):
                scores[a] -= 1000
        elif t in ("hora", "ryukyoku"):
            dl = e.get("deltas")
            if scores is not None and isinstance(dl, list) and len(dl) == len(scores):
                scores = [scores[i] + int(dl[i]) for i in range(len(scores))]
    seat = report.get("player_id")
    if scores is None or not isinstance(seat, int) or not (0 <= seat < len(scores)):
        return None, None
    return place_order(scores, oya).index(seat) + 1, scores[seat]
