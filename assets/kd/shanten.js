/**
 * 向听数计算 —— mortal-coach 自有实现（MIT）。
 *
 * 牌张用长度 38 的数组表示：1~9 万、11~19 筒、21~29 索、31~37 字牌，
 * 索引 0 / 10 / 20 / 30 不存牌。本文件不引用任何第三方牌理库：
 * 算法与 `scripts/mjcalc.py` 的 `_shanten_regular` / `_shanten_chiitoi` /
 * `_shanten_kokushi` 同源（同一套枚举规则，由本项目维护），
 * 前端与后端因此共用同一口径。
 */

export { calculateMinimumShanten, calculateStandardShanten }

const CAP = 5            // 手牌内最多容纳 4 个面子 + 1 个雀头
const SENTINEL = -2      // 调用方未指定下限时的默认值
const NEVER = -1         // 不剪枝：只要结果 >= -1 就继续找

/** 38 位手牌 → 34 位计数（万筒索各 9 + 字牌 7）。返回新数组，调用方可以随意改。 */
function counts34(hand) {
    const c = new Uint8Array(34)
    for (let i = 1; i < 38; i++) {
        const n = hand[i]
        if (!n) continue
        const base = i < 10 ? 0 : i < 20 ? 9 : i < 30 ? 18 : 27
        c[base + (i % 10) - 1] += n
    }
    return c
}

/** 七对子向听：差几个对子，再加种类不足 7 的罚款。和牌为 -1。 */
function chiitoiShanten(c) {
    let pairs = 0
    let kinds = 0
    for (let i = 0; i < 34; i++) {
        if (c[i] === 0) continue
        kinds++
        if (c[i] >= 2) pairs++
    }
    return 6 - pairs + (kinds < 7 ? 7 - kinds : 0)
}

/** 国士向听：13 种幺九字牌里差几张，有一对可少一巡。 */
function kokushiShanten(c) {
    const YAOCHU = [0, 8, 9, 17, 18, 26, 27, 28, 29, 30, 31, 32, 33]
    let kinds = 0
    let hasPair = 0
    for (const i of YAOCHU) {
        if (c[i] === 0) continue
        kinds++
        if (c[i] >= 2) hasPair = 1
    }
    return 13 - kinds - hasPair
}

/**
 * 普通型（4 面子 + 1 将）向听。深度优先枚举「这一张能当什么用」，
 * 取 8 - 2×面子 - 搭子 - 雀头 的最小值。搭子数受剩余面子数限制。
 *
 * floor 是剪枝下限：一旦当前最好结果已经 <= floor，就没有继续找的意义
 * （调用方只关心「会不会比 floor 更好」）。
 */
function regularShanten(c, floor) {
    let best = 8

    function walk(i, sets, taatsu, head) {
        if (best <= floor) return

        while (i < 34 && c[i] === 0) i++
        if (i === 34 || sets + taatsu + head >= CAP) {
            const usable = Math.min(taatsu, 4 - sets)
            const value = 8 - 2 * sets - usable - head
            if (value < best) best = value
            return
        }

        const n = c[i]
        const rank = i % 9

        // 刻子
        if (n >= 3) {
            c[i] = n - 3
            walk(i, sets + 1, taatsu, head)
            c[i] = n
        }
        // 顺子（字牌不参战，且不能跨花色成顺）
        if (i < 27 && rank <= 6 && c[i + 1] && c[i + 2]) {
            c[i]--; c[i + 1]--; c[i + 2]--
            walk(i, sets + 1, taatsu, head)
            c[i]++; c[i + 1]++; c[i + 2]++
        }
        // 对子：可当雀头，也可当搭子
        if (n >= 2) {
            c[i] = n - 2
            if (!head) walk(i, sets, taatsu, 1)
            walk(i, sets, taatsu + 1, head)
            c[i] = n
        }
        // 两面 / 边张
        if (i < 27 && rank <= 7 && c[i + 1]) {
            c[i]--; c[i + 1]--
            walk(i, sets, taatsu + 1, head)
            c[i]++; c[i + 1]++
        }
        // 嵌张
        if (i < 27 && rank <= 6 && c[i + 2]) {
            c[i]--; c[i + 2]--
            walk(i, sets, taatsu + 1, head)
            c[i]++; c[i + 2]++
        }
        // 这一张不参与任何组合
        c[i] = n - 1
        walk(i, sets, taatsu, head)
        c[i] = n
    }

    walk(0, 0, 0, 0)
    return best
}

/**
 * 只看普通型（不看七对子 / 国士），供「打掉哪张进张最多」的快速判定使用。
 * minimumShanten 传了有效值时会提前收工，返回值仍然 <= 该值。
 */
function calculateStandardShanten(handToCheck, minimumShanten = SENTINEL) {
    const floor = minimumShanten === SENTINEL ? NEVER : minimumShanten
    return regularShanten(counts34(handToCheck), floor)
}

/** 三种牌型里最小的向听（和牌 -1、听牌 0）。 */
function calculateMinimumShanten(handToCheck, minimumShanten = SENTINEL) {
    const c = counts34(handToCheck)

    const chiitoi = chiitoiShanten(c)
    if (chiitoi < 0) return chiitoi           // 七对子和牌，不可能更小

    const kokushi = kokushiShanten(c)
    if (kokushi < 3) return kokushi           // 国士很近时直接采用（历史行为，保持一致）

    const floor = minimumShanten === SENTINEL ? NEVER : minimumShanten
    return Math.min(regularShanten(c, floor), chiitoi, kokushi)
}
