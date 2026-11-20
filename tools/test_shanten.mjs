// 向听实现回归：读 tests/shanten_cases.json（输入手牌 + 期望值），逐例校验。
// 这些期望值由本项目实现产出，并与重写前的实现逐例对拍一致（3600 组随机手牌、0 差异）。
import { readFileSync } from 'node:fs'
import { calculateMinimumShanten, calculateStandardShanten } from '../assets/kd/shanten.js'
import { calculateUkeire } from '../assets/kd/efficiency.js'

const cases = JSON.parse(readFileSync(new URL('../tests/shanten_cases.json', import.meta.url), 'utf8'))

let pass = 0
const fails = []
for (const c of cases) {
    const hand = c.hand.split('').map(Number)
    const min = calculateMinimumShanten(hand)
    const std = calculateStandardShanten(hand)
    if (min === c.min && std === c.standard) pass++
    else fails.push({ note: c.note, hand: c.hand, want: [c.min, c.standard], got: [min, std] })
}

// 额外检查：剪枝口径（调用方靠这两个判定）
let pruneOk = 0, pruneBad = []
for (const c of cases) {
    const hand = c.hand.split('').map(Number)
    const base = calculateStandardShanten(hand)
    if (calculateStandardShanten(hand, base - 1) < base) { /* 正常：能到 base-1 */ }
    if (calculateStandardShanten(hand, base) !== base) {
        pruneBad.push({ note: c.note, hand: c.hand, base })
    } else pruneOk++
}

// 进张自洽性：列出来的每张牌摸到后向听确实下降，value 等于这些牌的剩余数之和
let ukeOk = 0
const ukeBad = []
for (const c of cases.slice(0, 80)) {
    const hand = c.hand.split('').map(Number)
    const rest = new Array(38).fill(0)
    for (let t = 1; t < 38; t++) {
        if (t % 10 === 0) continue
        rest[t] = Math.max(0, 4 - hand[t])
    }
    const base = calculateMinimumShanten(hand)
    const r = calculateUkeire(hand.slice(), rest, calculateMinimumShanten)
    const sum = r.tiles.reduce((a, t) => a + rest[t], 0)
    let ok = r.value === sum
    for (const t of r.tiles) {
        hand[t]++
        if (calculateMinimumShanten(hand) >= base) ok = false
        hand[t]--
    }
    if (ok) ukeOk++
    else ukeBad.push({ note: c.note, hand: c.hand, value: r.value, sum })
}
for (const f of ukeBad.slice(0, 5)) console.log(`UKEIRE FAIL ${f.note} hand=${f.hand}`)

for (const f of fails.slice(0, 5)) {
    console.log(`FAIL ${f.note} hand=${f.hand} want=${f.want} got=${f.got}`)
}
for (const f of pruneBad.slice(0, 5)) {
    console.log(`PRUNE FAIL ${f.note} hand=${f.hand} base=${f.base}`)
}

console.log(`${pass}/${cases.length} 向听用例一致，剪枝口径 ${pruneOk}/${cases.length}，进张自洽 ${ukeOk}/80`)
if (fails.length || pruneBad.length || ukeBad.length) process.exit(1)
