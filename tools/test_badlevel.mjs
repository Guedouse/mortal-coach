// 恶手分级单测：node tools/test_badlevel.mjs
// 直接 require 浏览器那份 badlevel.js（它同时导出 CommonJS），保证页面与测试同一实现。
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
const BL = require('../assets/kd/badlevel.js')

let failed = 0
function eq(name, got, want) {
    const ok = JSON.stringify(got) === JSON.stringify(want)
    if (!ok) { failed++; console.log(`  FAIL ${name}: got ${JSON.stringify(got)} want ${JSON.stringify(want)}`) }
    else console.log(`  ok   ${name}`)
}

// —— 默认：门槛 10pt，门槛之上只分严重 / 中等 ——
const d = BL.normalize(null)
eq('默认门槛 0.10', d.thresh, 0.10)
eq('默认严重线 0.50', d.gap.severe, 0.50)
eq('默认 Q 损失 严重 0.70', d.loss.severe, 0.70)
eq('默认 Q 损失 中等 0.30', d.loss.medium, 0.30)
eq('归一后没有 levels 那一层', 'levels' in d, false)

// —— 两档：只看权重差，不再有轻微 ——
eq('gap 97 分 → 严重', BL.levelOf({ gap: 0.97, qloss: -0.2 }, d), 'severe')
eq('gap 50 分 → 严重（含边界）', BL.levelOf({ gap: 0.50, qloss: -0.2 }, d), 'severe')
eq('gap 40 分 → 中等', BL.levelOf({ gap: 0.40, qloss: -0.03 }, d), 'medium')
eq('gap 10 分 → 中等（刚过门槛也算中等）', BL.levelOf({ gap: 0.10, qloss: -0.02 }, d), 'medium')
eq('gap 缺字段 → 中等（不会被判成第三档）', BL.levelOf({}, d), 'medium')

// —— 门槛：只是「收不收进库」，不参与分档 ——
eq('10 分够门槛', BL.inLibrary({ gap: 0.10 }, d), true)
eq('9 分不够门槛', BL.inLibrary({ gap: 0.09 }, d), false)
eq('门槛调高后 20 分不够', BL.inLibrary({ gap: 0.20 }, BL.normalize({ thresh: 0.3 })), false)

// —— 损失程度：只看 Q 损失，仍三档 ——
eq('Q 损 0.90 → 损失严重', BL.lossLevel({ gap: 0.4, qloss: -0.9 }, d), 'severe')
eq('Q 损 0.45 → 损失中等', BL.lossLevel({ gap: 0.4, qloss: -0.45 }, d), 'medium')
eq('Q 损 0.10 → 损失轻微', BL.lossLevel({ gap: 0.99, qloss: -0.10 }, d), 'minor')
eq('Q 损缺失 → 损失轻微', BL.lossLevel({ gap: 0.99 }, d), 'minor')
eq('lossOf 取绝对值', BL.lossOf({ qloss: -0.62 }), 0.62)
eq('权重差严重但损失轻微',
    [BL.levelOf({ gap: 0.99, qloss: -0.1 }, d), BL.lossLevel({ gap: 0.99, qloss: -0.1 }, d)],
    ['severe', 'minor'])

// —— 两套刻度各改各的，互不串台 ——
const c1 = BL.normalize({ gap: { severe: 0.8 } })
eq('只改严重线 → Q 保持默认', c1.loss, { severe: 0.70, medium: 0.30 })
eq('只改严重线 → 90 分算严重', BL.levelOf({ gap: 0.9, qloss: 0 }, c1), 'severe')
eq('只改严重线 → 70 分算中等', BL.levelOf({ gap: 0.7, qloss: 0 }, c1), 'medium')
eq('只改门槛 → 严重线保持默认', BL.normalize({ thresh: 0.25 }).gap.severe, 0.50)
const c2 = BL.normalize({ loss: { severe: 1.2, medium: 0.6 } })
eq('只改 Q → 门槛保持默认', c2.thresh, 0.10)
eq('只改 Q → 0.8 只算中等', BL.lossLevel({ gap: 0.9, qloss: -0.8 }, c2), 'medium')
eq('改 Q 不影响导航档', BL.levelOf({ gap: 0.9, qloss: -1.3 }, c2), 'severe')

// —— 旧配置迁移 ——
const old = BL.normalize({ metric: 'qloss', severe: 0.9, medium: 0.2 })
eq('旧 qloss 配置迁到 loss', old.loss, { severe: 0.9, medium: 0.2 })
eq('旧 qloss 配置的门槛用默认', old.thresh, 0.10)
const old2 = BL.normalize({ metric: 'gap', severe: 0.95, medium: 0.15 })
eq('旧 gap 配置 → medium 变门槛', old2.thresh, 0.15)
eq('旧 gap 配置 → severe 保留', old2.gap.severe, 0.95)
// 上一版三档配置（gap.medium 即门槛）
const old3 = BL.normalize({ gap: { severe: 0.50, medium: 0.10 }, loss: { severe: 0.70, medium: 0.30 } })
eq('上一版三档配置 → 门槛 0.10', old3.thresh, 0.10)
eq('上一版三档配置 → 严重 0.50', old3.gap.severe, 0.50)

// —— 写反 / 超界要自愈 ——
const inv = BL.normalize({ thresh: 0.6, gap: { severe: 0.2 } })
eq('严重线低于门槛 → 抬到门槛之上', inv.gap.severe > inv.thresh, true)
eq('Q 倒置 → 中等下调', BL.normalize({ loss: { severe: 0.3, medium: 0.9 } }).loss.medium, 0.29)
eq('超过 1 被夹住', BL.normalize({ gap: { severe: 99 } }).gap.severe, 1)
eq('负数被夹住', BL.normalize({ thresh: -3 }).thresh, 0)

// —— 汇总 + 文案 ——
const moves = [{ gap: 0.99, qloss: -1 }, { gap: 0.35, qloss: -0.4 }, { gap: 0.12, qloss: -0.02 }]
eq('summary 两档', BL.summary(moves, d), { severe: 1, medium: 2, total: 3 })
eq('fmtGap', BL.fmtGap({ gap: 0.973 }), '权重差 97pt')
eq('fmtQ', BL.fmtQ({ qloss: -0.62 }), 'Q 损失 0.62')
eq('fmtGapThr', BL.fmtGapThr(0.5), '50%')
eq('fmtQThr', BL.fmtQThr(0.7), '0.70')
eq('档位排序 严重>中等', BL.order('severe') > BL.order('medium'), true)

console.log(failed ? `\n${failed} 项失败` : '\n全部通过')
process.exit(failed ? 1 : 0)
