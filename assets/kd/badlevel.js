/* 恶手分级：一个可调门槛 + 两套互不相干的刻度。页面、设置面板与 node 单测共用这一份实现。
 *
 * ① 门槛 thresh —— 权重差低于它的手根本不进库（extract_core 提取时按它过滤）。
 *                   默认 10%，可在设置里改；改完要重跑流水线才对已有牌谱生效。
 *                   门槛之上的手**全部出解读、全部标记**，不再有「轻微但不算」这一档。
 * ② gap  —— 权重差。门槛之上只分两档：≥ severe（默认 50%）叫严重，其余叫中等。
 *            只决定「巡目下拉的颜色」（红 / 橙），两档都是恶手，都计数、都能跳。
 * ③ loss —— 期望损失 Q。只决定右上角徽章上的「损失 严重 / 中等 / 轻微」，
 *            和颜色无关，也不影响「恶手 N 处」。
 *
 * gap 与 loss 经常对不上：Mortal 100% 选这张（权重差 100pt），但两张牌其实差不多
 * （Q 损 0.1）。所以分开设置、分开显示，不给用户一个「综合分」。
 */
(function (root) {
    'use strict';

    var DEFAULTS = {
        thresh: 0.10,               // 入库门槛：权重差 ≥ 10%
        gap: { severe: 0.50 },      // 门槛之上：≥50% 严重，其余中等
        loss: { severe: 0.70, medium: 0.30 }
    };
    var ZH = { severe: '严重', medium: '中等', minor: '轻微' };
    var ORDER = { severe: 2, medium: 1, minor: 0 };

    function num(v, d) {
        v = Number(v);
        return isFinite(v) ? v : d;
    }

    function clamp(v) {
        v = num(v, 0);
        return v < 0 ? 0 : (v > 1 ? 1 : v);
    }

    function r2(v) { return Math.round(v * 100) / 100; }

    /** 把配置归一成 { thresh, gap:{severe}, loss:{severe,medium} }。
     *  兼容旧写法：
     *    · `{metric, severe, medium}`        —— 早期一维刻度；
     *    · `{gap:{severe,medium}, loss:{…}}` —— 上一版「严重/中等/轻微」三档，
     *      那里的 gap.medium 其实就是入库门槛，迁到 thresh。 */
    function normalize(cfg) {
        cfg = cfg || {};
        var out = {
            thresh: DEFAULTS.thresh,
            gap: { severe: DEFAULTS.gap.severe },
            loss: { severe: DEFAULTS.loss.severe, medium: DEFAULTS.loss.medium }
        };
        if (cfg.metric && !cfg.gap && !cfg.loss) {
            if (cfg.metric === 'qloss') {          // 早期只有 Q 刻度
                if (cfg.severe != null) out.loss.severe = clamp(cfg.severe);
                if (cfg.medium != null) out.loss.medium = clamp(cfg.medium);
            } else {                               // 早期按权重差：medium 就是门槛
                if (cfg.medium != null) out.thresh = clamp(cfg.medium);
                if (cfg.severe != null) out.gap.severe = clamp(cfg.severe);
            }
        }
        if (cfg.thresh != null) out.thresh = clamp(cfg.thresh);
        if (cfg.gap && typeof cfg.gap === 'object') {
            if (cfg.gap.severe != null) out.gap.severe = clamp(cfg.gap.severe);
            // 旧三档配置里的 gap.medium 就是门槛
            if (cfg.thresh == null && cfg.gap.medium != null) out.thresh = clamp(cfg.gap.medium);
        }
        if (cfg.loss && typeof cfg.loss === 'object') {
            if (cfg.loss.severe != null) out.loss.severe = clamp(cfg.loss.severe);
            if (cfg.loss.medium != null) out.loss.medium = clamp(cfg.loss.medium);
        }
        // 严重线必须落在门槛之上，否则「严重」这一档永远为空
        if (out.gap.severe <= out.thresh) out.gap.severe = r2(Math.min(1, out.thresh + 0.01));
        // Q 刻度：严重必须高于中等
        if (out.loss.severe <= out.loss.medium) {
            out.loss.medium = r2(Math.max(0, out.loss.severe - 0.01));
        }
        return out;
    }

    /** 权重差（正数，0~1）。 */
    function gapOf(move) { return Math.abs(num(move && move.gap, 0)); }

    /** 期望损失（正数）。数据里存的是 Q_act − Q_exp，所以取绝对值。 */
    function lossOf(move) { return Math.abs(num(move && move.qloss, 0)); }

    /** 门槛之上只分两档：≥ severe 严重，其余中等。 */
    function levelOf(move, cfg) {
        return gapOf(move) >= normalize(cfg).gap.severe ? 'severe' : 'medium';
    }

    /** 损失程度：只看 Q 损失，仍是三档（徽章用）。 */
    function lossLevel(move, cfg) {
        var c = normalize(cfg).loss;
        var v = lossOf(move);
        if (v >= c.severe) return 'severe';
        if (v >= c.medium) return 'medium';
        return 'minor';
    }

    /** 这一手够不够入库。页面用不到（库里天然都够），留给工具与测试对齐口径。 */
    function inLibrary(move, cfg) { return gapOf(move) >= normalize(cfg).thresh; }

    function order(level) { return ORDER[level] || 0; }
    function zh(level) { return ZH[level] || ''; }

    /** 「权重差 97pt」 */
    function fmtGap(move) { return '权重差 ' + Math.round(gapOf(move) * 100) + 'pt'; }
    /** 「Q 损失 0.62」 */
    function fmtQ(move) { return 'Q 损失 ' + lossOf(move).toFixed(2); }

    /** 阈值怎么显示：权重差按百分比，Q 损失按小数。 */
    function fmtGapThr(v) { return Math.round(Number(v) * 100) + '%'; }
    function fmtQThr(v) { return Number(v).toFixed(2); }

    /** 一批 moves 的分档计数（设置面板里的「按当前阈值整库多少手」用）。 */
    function summary(moves, cfg) {
        cfg = normalize(cfg);
        var out = { severe: 0, medium: 0, total: 0 };
        var list = Array.isArray(moves) ? moves
            : Object.keys(moves || {}).map(function (k) { return moves[k]; });
        for (var i = 0; i < list.length; i++) {
            out[levelOf(list[i], cfg)]++;
            out.total++;
        }
        return out;
    }

    var API = {
        DEFAULTS: DEFAULTS,
        ZH: ZH,
        normalize: normalize,
        gapOf: gapOf,
        lossOf: lossOf,
        levelOf: levelOf,
        lossLevel: lossLevel,
        inLibrary: inLibrary,
        order: order,
        zh: zh,
        fmtGap: fmtGap,
        fmtQ: fmtQ,
        fmtGapThr: fmtGapThr,
        fmtQThr: fmtQThr,
        summary: summary
    };
    root.BadLevel = API;
    if (typeof module !== 'undefined' && module.exports) module.exports = API;
})(typeof window !== 'undefined' ? window : globalThis);
