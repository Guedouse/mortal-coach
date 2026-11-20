# -*- coding: utf-8 -*-
"""日麻向听 / 进张 计算（自建，用于解读）。calls = 已副露（吃碰杠）的面子数。"""
from collections import Counter

HONORS = {"E": 27, "S": 28, "W": 29, "N": 30, "P": 31, "F": 32, "C": 33}
IDX2TILE = ([f"{n}m" for n in range(1, 10)] + [f"{n}p" for n in range(1, 10)] +
            [f"{n}s" for n in range(1, 10)] + ["E", "S", "W", "N", "P", "F", "C"])


def t2i(t):
    if t in HONORS:
        return HONORS[t]
    return {"m": 0, "p": 9, "s": 18}[t[1]] + int(t[0]) - 1


def i2t(i):
    return IDX2TILE[i]


def counts_of(tiles):
    c = [0] * 34
    for t in tiles:
        c[t2i(t)] += 1
    return c


def _shanten_regular(c, calls=0):
    best = [8]
    CAP = 5 - calls          # 手牌里最多再容纳 (4-calls) 个面子 + 1 个雀头

    def dfs(i, m, p, head):
        while i < 34 and c[i] == 0:
            i += 1
        if i == 34 or m + p + head >= CAP:
            mm = min(m + calls, 4)
            pp = min(p, 4 - mm)
            sh = 8 - 2 * mm - pp - (1 if head else 0)
            if sh < best[0]:
                best[0] = sh
            return
        if c[i] >= 3:
            c[i] -= 3; dfs(i, m + 1, p, head); c[i] += 3
        if i < 27 and i % 9 <= 6 and c[i + 1] and c[i + 2]:
            c[i] -= 1; c[i + 1] -= 1; c[i + 2] -= 1
            dfs(i, m + 1, p, head)
            c[i] += 1; c[i + 1] += 1; c[i + 2] += 1
        if c[i] >= 2:
            c[i] -= 2
            if not head:
                dfs(i, m, p, 1)
            dfs(i, m, p + 1, head)
            c[i] += 2
        if i < 27:
            r = i % 9
            if r <= 7 and c[i + 1]:
                c[i] -= 1; c[i + 1] -= 1; dfs(i, m, p + 1, head); c[i] += 1; c[i + 1] += 1
            if r <= 6 and c[i + 2]:
                c[i] -= 1; c[i + 2] -= 1; dfs(i, m, p + 1, head); c[i] += 1; c[i + 2] += 1
        c[i] -= 1; dfs(i, m, p, head); c[i] += 1

    dfs(0, 0, 0, 0)
    return best[0]


def _shanten_chiitoi(c):
    pairs = sum(1 for x in c if x >= 2)
    kinds = sum(1 for x in c if x >= 1)
    return 6 - pairs + max(0, 7 - kinds)


def _shanten_kokushi(c):
    ys = [0, 8, 9, 17, 18, 26, 27, 28, 29, 30, 31, 32, 33]
    kinds = sum(1 for i in ys if c[i] >= 1)
    has_pair = any(c[i] >= 2 for i in ys)
    return 13 - kinds - (1 if has_pair else 0)


def shanten(tiles, calls=0):
    c = counts_of(tiles)
    best = _shanten_regular(c[:], calls)
    if calls == 0:
        best = min(best, _shanten_chiitoi(c), _shanten_kokushi(c))
    return best


def ukeire(tiles, calls=0, visible=None):
    """返回 (向听数, {牌: 考虑场上已见后剩余枚数})。visible: {牌: 场见枚数}"""
    base = shanten(tiles, calls)
    c = counts_of(tiles)
    vis = [0] * 34
    if visible:
        for t, n in visible.items():
            vis[t2i(t)] += n
    res = {}
    for i in range(34):
        if c[i] + vis[i] >= 4:
            continue
        c[i] += 1
        ts = []
        for j in range(34):
            ts += [i2t(j)] * c[j]
        s = shanten(ts, calls)
        c[i] -= 1
        if s < base:
            res[i2t(i)] = 4 - c[i] - vis[i]
    return base, res
