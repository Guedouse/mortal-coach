/**
 * 进张（受入）计算 —— mortal-coach 自有实现（MIT）。
 *
 * 和 `scripts/mjcalc.py` 的 `ukeire()` 是同一件事：摸到哪张牌能让向听数下降，
 * 以及场上还剩几张。这里只按「摸一张再算一次向听」做判定，不引入任何外部牌理库。
 */

/**
 * @param {number[]} hand            38 位手牌（0 / 10 / 20 / 30 位不用）
 * @param {number[]} remainingTiles  38 位「场上还剩几张」，与 hand 同长度
 * @param {Function} shantenFunction 向听函数（如 calculateMinimumShanten）
 * @param {number} [baseShanten]     手牌当前向听；传 -2 表示现算
 * @returns {{value:number, tiles:number[]}} value = 有效进张张数，tiles = 牌码数组
 */
export function calculateUkeire(hand, remainingTiles, shantenFunction, baseShanten = -2) {
    const base = baseShanten === -2 ? shantenFunction(hand) : baseShanten
    const work = hand.slice()

    let value = 0
    const tiles = []

    for (let t = 1; t < work.length; t++) {
        if (t % 10 === 0) continue                 // 占位位（0/10/20/30）不是牌
        const left = remainingTiles[t] || 0
        if (left <= 0) continue

        work[t]++
        // 只关心「是否比现在更好」，传 base - 1 让向听函数提前收工
        const after = shantenFunction(work, base - 1)
        work[t]--

        if (after < base) {
            value += left
            tiles.push(t)
        }
    }

    return { value, tiles }
}
