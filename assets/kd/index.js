"use strict";

import { calculateMinimumShanten, calculateStandardShanten } from "./shanten.js";
import { calculateUkeire } from "./efficiency.js"

class GlobalState {
    constructor() {
        this.ui = new UI
        this.fullData = null // Full json -- maybe split this up some, super redundant!
        this.gs = null // current round GameState
        this.ge = null // array of array of GameEvent

        this.ply_counter = 0
        this.hand_counter = 0
        this.json_data = null
        this.heroPidx = null   // player index mortal reviewed
        this.showHands = false
        this.showMortal = true
        this.showDealinRate = null // set by localStorage
        this.uiConnected = false

        // calcCombos Weights
        // penchan anchor at 1
        this.C_ccw_ryanmen = 3.5
        this.C_ccw_honorTankiShanpon = 1.7
        this.C_ccw_nonHonorTankiShanpon = 1.0
        this.C_ccw_kanchan = 0.21
        this.C_ccw_kanchanRiichiSujiTrap = 2.6
        this.C_ccw_uraSuji = 1.3
        this.C_ccw_matagiSujiEarly = 0.6
        this.C_ccw_matagiSujiRiichi = 1.2
        this.C_ccw_doraGreed = 1.2
        this.C_ccw_akaDiscard = 0.14

        this.C_soft_T = 2

        this.mediaBreak = getComputedStyle(document.documentElement).getPropertyValue('--media-break')
        this.updateZoom()

        this.C_db_height = 50
        this.C_db_dealinMax = 15
        this.C_db_totWidth = 605
        this.C_db_handPadding = 5
        this.C_db_tileWidth = 34
        this.C_db_tileHeight = 44
        this.C_db_heroBarWidth = 20
        this.C_db_mortBarWidth = 10
        this.C_cb_heroBarHeight = this.C_db_height // maybe don't need separate one...
        this.C_cb_mortBarHeightRatio = 0.9
        this.C_cb_padding = 10
        this.C_cb_widthFactor = 1.5
        this.C_cb_maxShown = 4

        this.C_colorText = getComputedStyle(document.documentElement).getPropertyValue('--color-text')
        this.C_colorBarMortal = getComputedStyle(document.documentElement).getPropertyValue('--color-bar-mortal')
        this.C_colorBarHero = getComputedStyle(document.documentElement).getPropertyValue('--color-bar-hero')
        this.C_colorTsumogiri = getComputedStyle(document.documentElement).getPropertyValue('--color-tsumogiri')
        this.C_colorTileBg = getComputedStyle(document.documentElement).getPropertyValue('--color-tile-bg')
        this.C_colorOpps = [getComputedStyle(document.documentElement).getPropertyValue('--color-shimo'),
                            getComputedStyle(document.documentElement).getPropertyValue('--color-toimen'),
                            getComputedStyle(document.documentElement).getPropertyValue('--color-kami')]
        this.C_windStr = ['E', 'S', 'W', 'N']

        this.alphaTestMode = false
    }
    updateZoom() {
        const H = window.innerHeight || screen.height
        const W = window.innerWidth || screen.width
        if (W <= 900) {
            this.C_zoom = window.matchMedia("(orientation: portrait)").matches
                ? W / 655 : (H - 50) / 675
        } else {
            // 桌面窗口：牌桌按高度先撑满，再用「牌桌 + 侧栏 + 解读面板」的宽度收一收
            const byH = (H - 30) / 735
            const byW = (W - 610 - 90) / (655 + 290)
            this.C_zoom = Math.max(0.8, Math.min(1.35, Math.min(byH, byW)))
        }
        document.documentElement.style.setProperty('--zoom', this.C_zoom)
        this.C_zoomTiles =  (34*this.C_zoom - 4) / (34-4)
    }
}

class GameState {
    constructor(log) {
        let logIdx = 0
        this.rawRound = log[logIdx++]
        this.roundWind = Math.floor(this.rawRound[0]/4) + tm2t('e')
        this.dealerIdx = this.rawRound[0] % 4
        this.roundNum = this.dealerIdx
        this.honbas = this.rawRound[1]
        this.prevRoundSticks = this.rawRound[2]
        this.thisRoundSticks = [0,0,0,0]
        this.thisRoundExtraDoras = 0
        this.tilesLeft = 70
        this.scores = log[logIdx++]
        this.doraIndicator = log[logIdx++]
        this.dora = this.doraIndicator.map(doraIndicator2dora)
        this.uradora = log[logIdx++]
        this.hands = []
        this.draws = []
        this.discards = []
        this.discardPond = [[],[],[],[]]
        for (let pnum=0; pnum<4; pnum++) {
            this.hands.push(Array.from(log[logIdx++]))
            this.draws.push(log[logIdx++])
            this.discards.push(log[logIdx++])
        }
        this.resultArray = log[logIdx++]
        this.result = this.resultArray[0]
        this.scoreChanges = [0,0,0,0]
        this.winner = []
        this.payer = []
        this.pao = []
        this.yakuStrings = []
        let idx = 1
        let s = this.resultArray[idx]
        while(this.resultArray[idx]) {
            this.scoreChanges = this.scoreChanges.map((a, i) => a+this.resultArray[idx][i])
            idx++
            if (this.resultArray[idx]) {
                this.winner.push(this.resultArray[idx][0])
                this.payer.push(this.resultArray[idx][1])
                this.pao.push(this.resultArray[idx][2]) // TODO: Find an example of this
                this.yakuStrings.push(this.resultArray[idx].slice(3))
            }
            idx++
        }
        this.drawnTile = [null, null, null, null]
        this.calls = [[],[],[],[]]
        this.handOver = false
        this.genbutsu = [new Set, new Set, new Set, new Set]
        this.discardsToRiichi = [[],[],[],[]]
        this.reach_accepted = [false, false, false, false]
        this.unseenTiles = []
        for (let pidx=0; pidx<4; pidx++) {
            this.unseenTiles[pidx] = initUnseenTiles(pidx, this)
        }
    }
}

class UI {
    constructor() {
        this.hands = [[],[],[],[]]
        this.calls = [[],[],[],[]]
        this.discards = [[],[],[],[]]
        this.pInfo = [[],[],[],[]]
        this.pInfoResult = [[],[],[],[]]
        this.gridInfo = document.querySelector('.grid-info')
        this.round = document.querySelector('.info-round')
        this.tilesLeft = document.querySelector('.info-tiles-left')
        this.doras = document.querySelector('.info-doras')
        this.aboutModal = document.querySelector('.about-modal')
        this.infoRoundModal = document.querySelector('.info-round-modal')
        this.infoRoundTable = document.querySelector('.info-round-table')
        this.infoThisRoundModal = document.querySelector('.info-this-round-modal')
        this.infoThisRoundTable = document.querySelector('.info-this-round-table')
        this.infoThisRoundClose = document.querySelector('.info-this-round-close')
        this.genericModal = document.getElementById('generic-modal')
        this.genericModalBody = document.querySelector('.generic-modal-body')
        this.optInfo = document.querySelector('.opt-info')
        this.setPovPidx(0)
    }
    setPovPidx(newPidx) {
        this.povPidx = newPidx
        for (let pidx=0; pidx<4; pidx++) {
            let tmpPovPidx = (4 + pidx - this.povPidx) % 4
            this.hands[pidx] = document.querySelector(`.hand-closed-p${tmpPovPidx}`)
            this.calls[pidx] = document.querySelector(`.hand-calls-p${tmpPovPidx}`)
            this.discards[pidx] = document.querySelector(`.grid-discard-p${tmpPovPidx}`)
            this.pInfo[pidx] = document.querySelector(`.gi-p${tmpPovPidx}`)
            this.pInfoResult[pidx] = document.querySelector(`.gi-p${tmpPovPidx}-result`)
        }
    }
    roundStr(showSticks) {
        let str = i18next.t(GS.C_windStr[GS.gs.roundWind-tm2t('e')])
        str += (GS.gs.roundNum+1)
        if (GS.gs.honbas > 0) {
            str += "-" + GS.gs.honbas
        }
        if (showSticks && GS.gs.prevRoundSticks>0) {
            str += " +" + GS.gs.prevRoundSticks*1000
        }
        return str
    }
    reset() {
        this.round.replaceChildren(this.roundStr(true))
        this.doras.replaceChildren()
        this.tilesLeft.replaceChildren()
        for (let pidx=0; pidx<4; pidx++) {
            this.discards[pidx].replaceChildren()
            let seatWind = (4 + pidx - GS.gs.roundNum) % 4
            this.pInfo[pidx].replaceChildren(i18next.t(GS.C_windStr[seatWind]))
            this.pInfo[pidx].append(' ', GS.gs.scores[pidx]-GS.gs.thisRoundSticks[pidx]*1000)
            this.pInfoResult[pidx].replaceChildren()
            this.pInfoResult[pidx].append(this.formatString(-GS.gs.thisRoundSticks[pidx]*1000, false, true))
        }
    }
    formatString(num, showZero, addPlus) {
        if (!showZero && num == 0) {
            return ''
        }
        let s = (addPlus && num>0) ? '+' : ''
        s += num
        return s
    }
    parseYakuString(yaku) {
        let s = yaku.split(/([\(\)])|([0-9]+)/)
        s = s.map(x => { return !x ? '' : x.match(/[0-9\-\(\)]/) ? x : i18next.t(x) })
        return s.join(' ')
    }
    getResultTypeStr() {
        let resultTypeStr = []
        for (let idx=0; idx==0||idx<GS.gs.winner.length; idx++) {
            if (GS.gs.result == '和了') {
                const winnerStr = relativeToHeroStr(GS.gs.winner[idx])
                if (GS.gs.winner[0] === GS.gs.payer[0]) {
                    resultTypeStr[idx] = i18next.t('tsumo-full', {winner:winnerStr})
                } else {
                    const loserStr = relativeToHeroStr(GS.gs.payer[idx])
                    resultTypeStr[idx] = i18next.t('ron-full', {winner:winnerStr, loser:loserStr})

                }
            } else {
                resultTypeStr[idx] = i18next.t(GS.gs.result)
            }
        }
        return resultTypeStr
    }
    getActionSpan(detail) {
        let actionSpan = document.createElement('span')
        let textContent = i18next.t(detail.action.type)
        if (detail.action.type == 'hora' && detail.action.actor != detail.action.target) {
           textContent = i18next.t('ron') // translate defaults to Tsumo. Change to Ron in this case            
        }
        actionSpan.innerHTML = textContent
        // Some kans include pai, some don't.
        let pai = detail.action.type.endsWith('kan') ? detail.action.consumed[0] : detail.action.pai
        if (pai) {
            let tiles = [pai]
            if (detail.action.consumed && !detail.action.type.endsWith('kan')) {
                tiles = detail.action.consumed
            }
            actionSpan.innerHTML += "&nbsp&nbsp&nbsp"
            for (let i=0; i<tiles.length; i++) {
                // let tileDiv = createTile(tenhou2str(detail.action.pai))
                let tileDiv = createTile(tenhou2str(tiles[i]))
                actionSpan.innerHTML += tileDiv.innerHTML
            }
        }
        return actionSpan
    }
    updateOptInfo() {
        let gameEvent = GS.ge[GS.hand_counter][GS.ply_counter]
        let mortalEval = gameEvent.mortalEval
        this.optInfo.replaceChildren()
        let actualTable = document.createElement("table")
        actualTable.classList.add('wider-table')
        actualTable.classList.add('hover-rows')
        this.optInfo.append(actualTable)
        let table = document.createElement("table")
        table.classList.add('wider-table')
        table.classList.add('hover-rows')
        this.optInfo.append(table)
        addTableRow(table, [i18next.t('Action'), i18next.t('Q'), i18next.t('P')])
        if (!GS.showMortal || !mortalEval) {
            addTableRow(actualTable, [i18next.t("Player"), ""])
            addTableRow(actualTable, [i18next.t("Mortal"), ""])
            return
        }

        addTableRow(actualTable, [i18next.t("Player"), this.getActionSpan(mortalEval.details[mortalEval.actual_index])])
        addTableRow(actualTable, [i18next.t("Mortal"), this.getActionSpan(mortalEval.details[0])])
    
        for (let [idx, detail] of mortalEval.details.entries()) {
            let actionSpan = this.getActionSpan(detail)
            let row = [actionSpan, detail.q_value.toFixed(2), (detail.prob*100).toFixed(2)]
            addTableRow(table, row)
        }
    }
    updateGridInfo() {
        this.clearDiscardBars()
        this.clearCallBars()
        let event = GS.ge[GS.hand_counter][GS.ply_counter]
        this.updateDiscardBars()
        this.updateCallBars()
        this.updateOptInfo()
        this.tilesLeft.append(`x${GS.gs.tilesLeft}`)
        if (event.mortalEval && event.mortalEval.tiles_left != GS.gs.tilesLeft) {
            console.log('tiles left mismatch:', event.mortalEval.tiles_left, GS.gs.tilesLeft)
        }
        for (let i=0; i<5; i++) {
            if (GS.gs.doraIndicator[i] == null || i > GS.gs.thisRoundExtraDoras) {
                this.doras.append(createTile('back'))
            } else {
                this.doras.append(createTile(tenhou2str(GS.gs.doraIndicator[i])))
            }
        }
        if (GS.gs.handOver) {
            this.infoThisRoundTable.replaceChildren()
            let table = document.createElement("table")
            let resultTypeStr = this.getResultTypeStr()
            for (let idx=0; idx==0||idx<GS.gs.winner.length; idx++) {
                if (idx>0) {
                    this.infoThisRoundTable.append(document.createElement("br"))
                }
                this.infoThisRoundTable.append(createParaElem(resultTypeStr[idx]))
                if (GS.gs.result == '和了') {
                    for (let yaku of GS.gs.yakuStrings[idx]) {
                        this.infoThisRoundTable.append(createParaElem(this.parseYakuString(yaku)))
                    }
                }
            }
            for (let pidx=0; pidx<4+1; pidx++) {
                let tr = table.insertRow()
                let cell = tr.insertCell()
                cell.textContent = `${relativeToHeroStr(pidx)}`
                cell = tr.insertCell()
                cell.textContent = `${event.scoreChangesPlusSticks[pidx]}`
            }
            table.style.margin = "10px auto"
            this.infoThisRoundTable.append(table)

            this.infoThisRoundModal.showModal()
            this.infoThisRoundModal.addEventListener('click', (event) => {
                this.infoThisRoundModal.close()
            })
            this.infoThisRoundClose.addEventListener('click', (event) => {
                this.infoThisRoundModal.close()
            })
        }
    }
    clearCallBars() {
        const callBars = document.querySelector('.killer-call-bars')
        let svgElement = document.createElementNS("http://www.w3.org/2000/svg", "svg")
        svgElement.setAttribute('style', `transform-origin: top left; transform: scale(${GS.C_zoom}); position:absolute`)
        callBars.replaceChildren(svgElement)
    }
    createTileSvg(x, y, tile) {
        if (isNaN(tile)) {
            console.log(tile)
            throw new Error()
        }
        const backgroundRect = document.createElementNS("http://www.w3.org/2000/svg", "rect")
        backgroundRect.setAttribute("x", x-1)
        backgroundRect.setAttribute("y", y-1)
        backgroundRect.setAttribute("width", "20")
        backgroundRect.setAttribute("height", "26")
        backgroundRect.setAttribute("fill", GS.C_colorTileBg)
        backgroundRect.setAttribute("rx", "2px")
        backgroundRect.setAttribute("ry", "2px")
        const tileSvg = document.createElementNS("http://www.w3.org/2000/svg", "image")
        tileSvg.setAttribute('href', `media/Regular_shortnames/${tenhou2str(tile)}.svg`)
        tileSvg.setAttribute("x", x)
        tileSvg.setAttribute("y", y)
        tileSvg.setAttribute("width", 18)
        return [backgroundRect, tileSvg]
    }
    updateCallBars() {
        let gameEvent = GS.ge[GS.hand_counter][GS.ply_counter]
        let mortalEval = gameEvent.mortalEval
        if (!GS.showMortal || !mortalEval) {
            return
        }
        const callBars = document.querySelector('.killer-call-bars')
        let svgElement = callBars.firstElementChild
        let slot = 0
        for (let [idx, detail] of mortalEval.details.entries()) {
            let Pval = detail.softNormProb*100
            let mortalDetail = !mortalEval.is_equal && idx==0
            if (detail.action.type == 'dahai' && !mortalDetail) {
                continue // Skip tiles (unless it's a mismatch)
            }
            if (slot>=GS.C_cb_maxShown-1 && !mortalDetail && mortalEval.actual_index != idx) {
                continue // Not enough room in GUI to show more
            }
            let xloc = GS.C_db_tileWidth*GS.C_cb_widthFactor/2 + slot*GS.C_db_tileWidth*GS.C_cb_widthFactor
            svgElement.appendChild(createRect(
                xloc-GS.C_db_mortBarWidth/2, GS.C_db_mortBarWidth, GS.C_cb_heroBarHeight, Pval/100*GS.C_cb_mortBarHeightRatio, GS.C_colorBarMortal
            ))
            let textContent = i18next.t(detail.action.type)
            if (detail.action.type == 'hora' && detail.action.actor != detail.action.target) {
                textContent = i18next.t('ron') // translate defaults to Tsumo. Change to Ron in this case            
            }
            let textElem = createSvgText(xloc-GS.C_db_mortBarWidth/2-10, GS.C_db_height + 20, textContent)
            svgElement.appendChild(textElem)
            if (mortalEval.actual_index == idx) {
                let bbox = textElem.getBBox()
                let rect = document.createElementNS("http://www.w3.org/2000/svg", "rect")
                rect.setAttribute("x", bbox.x - 3)
                rect.setAttribute("y", bbox.y - 3)
                rect.setAttribute("width", bbox.width + 6)
                rect.setAttribute("height", bbox.height + 6)
                rect.setAttribute("fill", "none")
                rect.setAttribute("stroke", "hsl(0, 70%, 50%)")
                rect.setAttribute("stroke-width", "2")
                svgElement.insertBefore(rect, textElem)
            }

            // Some kans include pai, some don't.
            let pai = detail.action.type.endsWith('kan') ? detail.action.consumed[0] : detail.action.pai
            if (pai) {
                let tiles = [pai]
                if (detail.action.consumed && !detail.action.type.endsWith('kan')) {
                    tiles = detail.action.consumed
                }
                let x_offset = tiles.length == 1 ? 25 : 35 // why did I use svgs and now I have to write my own layout code!
                for (let i=0; i<tiles.length; i++) {
                    let tileSvg = this.createTileSvg(xloc+(i+1)*20-GS.C_db_mortBarWidth/2-x_offset, GS.C_db_height + 30, tiles[i])
                    svgElement.appendChild(tileSvg[0])
                    svgElement.appendChild(tileSvg[1])
                }
            }
            slot++
        }
        if (!mortalEval.is_equal) {
            let xloc = GS.C_db_tileWidth*GS.C_cb_widthFactor/5 + slot*GS.C_db_tileWidth*GS.C_cb_widthFactor
            let textContent = (mortalEval.details[mortalEval.actual_index].normProb > .25) ? i18next.t("Hmm...") : i18next.t("Clack!")
            svgElement.appendChild(createSvgText(xloc-GS.C_db_mortBarWidth/2, 60, textContent))
        }
    }
    clearDiscardBars() {
        const discardBars = document.getElementById("discard-bars")
        let [discardSvgElem, dangerSvgElem] = discardBars.children
        if (discardSvgElem) {
            discardSvgElem.replaceChildren()
            dangerSvgElem.replaceChildren()
            return
        }
        let svgElement = document.createElementNS("http://www.w3.org/2000/svg", "svg")
        svgElement.setAttribute("width", GS.C_db_totWidth)
        svgElement.setAttribute("height", GS.C_db_height)
        svgElement.setAttribute('style', `transform-origin: top left; transform: scale(${GS.C_zoom})`)
        svgElement.classList.add('discard-bars-svg')
        discardBars.replaceChildren(svgElement)
        svgElement = document.createElementNS("http://www.w3.org/2000/svg", "svg")
        svgElement.setAttribute("width", GS.C_db_totWidth)
        svgElement.setAttribute("height", GS.C_db_height)
        svgElement.setAttribute('style', `transform-origin: top left; transform: scale(${GS.C_zoom}, ${-GS.C_zoom}) translate(0, ${-1*(GS.C_db_height+GS.C_db_tileHeight)}px)`)
        svgElement.classList.add('danger-bars-svg')
        discardBars.append(svgElement)
    }
    updateDiscardBars() {
        let gameEvent = GS.ge[GS.hand_counter][GS.ply_counter]
        let mortalEval = gameEvent.mortalEval
        const discardBars = document.getElementById("discard-bars")
        let [discardSvgElem, dangerSvgElem] = discardBars.children
        if (!GS.showMortal) {
            discardSvgElem.appendChild(createSvgText(60,30,i18next.t("spoiler")))
            return
        }
        let showDangerBars = GS.showDealinRate && ('danger' in gameEvent)
        if (!mortalEval && !showDangerBars) {
            if (GS.showDealinRate) {
                dangerSvgElem.appendChild(createSvgText(60,30,i18next.t("dealin-riichi-only")))
                dangerSvgElem.lastChild.setAttribute('style', 'transform: translate(0, 50px) scale(1, -1)')
            }
            return // nothing to display
        }
        let atLeastOnedanger = false
        for (let i = -1; i < GS.gs.hands[GS.heroPidx].length; i++) {
            let tile = (i==-1) ? GS.gs.drawnTile[GS.heroPidx] : GS.gs.hands[GS.heroPidx][i]
            if (tile == null) {
                continue // on calls there was no drawnTile
            }
            let slot = (i !== -1) ? i : GS.gs.hands[GS.heroPidx].length+0.5
            let xloc = GS.C_db_handPadding + GS.C_db_tileWidth/2 + slot*GS.C_db_tileWidth
            if (mortalEval) {
                let matchingDetailIdx = mortalEval.details.findIndex(x => x.action && x.action.type == 'dahai' && x.action.pai && x.action.pai==tile)
                // TODO: Check code for this. For now assume due to illegal calls swaps
                if (matchingDetailIdx != -1) {
                    let matchingDetail = mortalEval.details[matchingDetailIdx]
                    let Pval = matchingDetail.softNormProb*100
                    if (matchingDetailIdx == mortalEval.actual_index) {
                        let tileDivs = this.hands[GS.heroPidx].querySelectorAll('div')
                        if (i==-1) {
                            tileDivs[tileDivs.length-1].lastChild.classList.add('tileImgHighlight')
                        } else {
                            tileDivs[i].lastChild.classList.add('tileImgHighlight')
                        }
                    }
                    discardSvgElem.appendChild(createRect(
                        xloc-GS.C_db_mortBarWidth/2, GS.C_db_mortBarWidth, GS.C_db_height, Pval/100*GS.C_cb_mortBarHeightRatio, GS.C_colorBarMortal
                    ));
                }
            }
            if (showDangerBars) {
                for (let tenpaiPidx=0; tenpaiPidx<4; tenpaiPidx++) {
                    if (tenpaiPidx == GS.heroPidx) {
                        continue
                    }
                    atLeastOnedanger = true
                    let relToHero = relativeToHero(tenpaiPidx)
                    let color = GS.C_colorOpps[relToHero-1]
                    let fakeDangers = false
                    // fakeDangers = true
                    let Pval
                    if (fakeDangers) {
                        Pval = 7*relToHero
                    } else {
                        let thisDanger = gameEvent['danger'][tenpaiPidx][GS.heroPidx]
                        if (!thisDanger) {
                            continue
                        }
                        let matchingCombo = thisDanger['combos'][normRedFive(tile)]
                        Pval = matchingCombo === undefined ? 0 : matchingCombo['all']/thisDanger['combos']['all']*100
                    }
                    let PvalZoom = Math.min(Pval*(100/GS.C_db_dealinMax), 100)
                    dangerSvgElem.appendChild(createRect(
                        xloc-(2.5-relToHero)*GS.C_db_mortBarWidth, GS.C_db_mortBarWidth, GS.C_db_height, PvalZoom/100*GS.C_cb_mortBarHeightRatio, color
                    ));
                }
            }
        }
        if (GS.showDealinRate && !atLeastOnedanger) {
            dangerSvgElem.appendChild(createSvgText(60,30,i18next.t("dealin-riichi-only")))
            dangerSvgElem.lastChild.setAttribute('style', 'transform: translate(0, 50px) scale(1, -1)')
        }
    }
    updateHandInfo() {
        for (let pidx=0; pidx<4; pidx++) {
            this.addHandTiles(pidx, 'hand', [], true)
            for (let tileInt of GS.gs.hands[pidx]) {
                // TODO: Draw and all tenpai could show the hands also?
                if (GS.showHands || (GS.gs.handOver && GS.gs.scoreChanges[pidx]>0) || pidx==GS.heroPidx) {
                    this.addHandTiles(pidx, 'hand', [tenhou2str(tileInt)], false)
                } else {
                    this.addHandTiles(pidx, 'hand', ['back'], false)
                }
            }
            this.addBlankSpace(pidx, true)
            if (GS.gs.drawnTile[pidx] != null) {
                if (GS.showHands || (GS.gs.handOver && GS.gs.scoreChanges[pidx]>0) || pidx==GS.heroPidx) {
                    this.addHandTiles(pidx, 'hand', [tenhou2str(GS.gs.drawnTile[pidx])], false)
                } else {
                    this.addHandTiles(pidx, 'hand', ['back'], false)
                }
            }
            if (GS.gs.calls[pidx].length > 0) {
                for (let tileInt of GS.gs.calls[pidx]) {
                    if (tileInt == 'rotate') {
                        this.rotateLastTile(pidx, 'hand')
                    } else if (tileInt == 'float') {
                        this.floatLastTile(pidx)
                    } else if (tileInt == 'back') {
                        this.addHandTiles(pidx, 'call', [tileInt], false)
                    } else {
                        this.addHandTiles(pidx, 'call', [tenhou2str(tileInt)], false)
                    }
                }
            }
        }
    }
    addHandTiles(pidx, type, tileStrArray, replace) {
        let div = type == 'call' ? this.calls[pidx] : this.hands[pidx]
        if (replace) {
            this.hands[pidx].replaceChildren()
            this.calls[pidx].replaceChildren()
        }
        for (let i in tileStrArray) {
            div.appendChild(createTile(tileStrArray[i]))
        }   
    }
    addDiscardTiles(pidx, tileStrArray, replace) {
        let div = this.discards[pidx]
        if (replace) {
            div.replaceChildren()
        }
        for (let i in tileStrArray) {
            // Add 4 blank placeholders for the first 2 rows of discards
            // The 3rd row will allow 4 overflow tiles
            // Then it overflows to the 4th row (and probably overlaps GUI stuff a bit)
            if (div.childElementCount == 6 || div.childElementCount == 12+4) {
                for (let j=0; j<4; j++) {
                    div.appendChild(createTile('Blank'))
                    div.lastChild.style.opacity = "0"
                }
            }
            div.appendChild(createTile(tileStrArray[i]))
        }   
    }
    rotateLastTile(pidx, type) {
        let div = (type=='hand') ? this.calls[pidx] : this.discards[pidx]
        div.lastChild.lastChild.classList.add('rotate')
    }
    floatLastTile(pidx) {
        let div = this.calls[pidx]
        div.lastChild.lastChild.classList.add('float')
    }
    addBlankSpace(pidx, narrow) {
        this.addHandTiles(pidx, 'hand', ['Blank'], false)
        this.hands[pidx].lastChild.style.opacity = "0"
        if (narrow) {
            this.hands[pidx].lastChild.classList.add('narrow')
        }
    }
    updateDiscardPond() {
        let event = GS.ge[GS.hand_counter][GS.ply_counter]
        // console.log('updateDiscardPond', event)
        for (let pidx=0; pidx<4; pidx++) {
            for (let tile of GS.gs.discardPond[pidx]) {
                this.addDiscard(pidx, [tenhou2str(tile.tile)], tile.tsumogiri, tile.riichi)
                if (tile.called) {
                    this.lastDiscardWasCalled(pidx)
                }
            }
            if (event.type=='dahai' && pidx==event.actor) {
                this.discards[pidx].lastChild.lastChild.classList.add('last-discard')
            }
        }
    }
    addDiscard(pidx, tileStrArray, tsumogiri, riichi) {
        this.addDiscardTiles(pidx, tileStrArray)
        if (tsumogiri) {
            this.discards[pidx].lastChild.lastChild.classList.add('tsumogiri')
        }
        if (riichi) {
            this.rotateLastTile(pidx, 'discard')
        }
    }
    lastDiscardWasCalled(pidx) {
        this.discards[pidx].lastChild.classList.add('called')
    }
    updateAbout() {
        let table = document.createElement("table")
        let metadata = document.querySelector('.about-metadata')
        metadata.replaceChildren(table)
        addTableRow(table, [i18next.t('Engine'), GS.fullData['engine']])
        addTableRow(table, [i18next.t('Model tag'), GS.fullData['review']['model_tag']])
        addTableRow(table, [i18next.t('Mjai-reviewer version'), GS.fullData['version']])
        addTableRow(table, [i18next.t('Game length'), i18next.t(GS.fullData['game_length'])])
        addTableRow(table, [i18next.t('Loading time'), GS.fullData['loading_time']])
        addTableRow(table, [i18next.t('Review time'), GS.fullData['review_time']])
        addTableRow(table, [i18next.t('Temperature'), GS.fullData['review']['temperature']])
        {
            let m = GS.fullData['review']['total_matches']
            let r = GS.fullData['review']['total_reviewed']
            let p = (m/r*100).toFixed(1)
            let s = `${m}/${r} = ${p}%`
            addTableRow(table, [i18next.t('Matches/total'), s])
        }
        addTableRow(table, [i18next.t('Rating'), (GS.fullData.review.rating*100).toFixed(1)])
    }
    updateResultsTable() {
        let table = document.createElement("table")
        this.infoRoundTable.replaceChildren(table)
        let hand_counter = 0
        let tr = table.insertRow()
        let cell = tr.insertCell()
        cell.textContent = i18next.t('Round')
        for (let i=0; i<2; i++) {
            for (let pidx=0; pidx<4+1; pidx++) {
                cell = tr.insertCell()
                cell.textContent = `${relativeToHeroStr(pidx)}`
            }
            if (i==0) {cell = tr.insertCell()}
        }
        for (let [roundNum, currGeList] of GS.ge.entries()) {
            GS.gs = new GameState(GS.fullData.split_logs[roundNum].log[0])
            let result = currGeList.slice(-1)[0]
            tr = table.insertRow()
            tr.addEventListener('click', () => {
                GS.hand_counter = roundNum
                GS.ply_counter = 0
                this.infoRoundModal.close()
                updateState()
            })
            cell = tr.insertCell()
            cell.textContent = this.roundStr(false)
            for (let pidx=0; pidx<4+1; pidx++) {
                cell = tr.insertCell()
                cell.textContent = pidx==4 ? GS.gs.prevRoundSticks*1000 : `${GS.gs.scores[pidx]}`
            }
            cell = tr.insertCell()
            for (let pidx=0; pidx<4+1; pidx++) {
                cell = tr.insertCell()
                cell.textContent = `${result.scoreChangesPlusSticks[pidx]}`
                if (result.scoreChangesPlusSticks[pidx] < -7000) {
                    cell.classList.add('big-loss')
                } else if (result.scoreChangesPlusSticks[pidx] < -3000) {
                    cell.classList.add('medium-loss')
                } else if (result.scoreChangesPlusSticks[pidx] > 7000) {
                    cell.classList.add('big-win')
                } else if (result.scoreChangesPlusSticks[pidx] > 3000) {
                    cell.classList.add('medium-win')
                }
            }
            hand_counter++
        }
        tr = table.insertRow()
        cell = tr.insertCell()
        cell.textContent = i18next.t("Final")
        let lastResult = GS.ge.slice(-1)[0].slice(-1)[0]
        for (let pidx=0; pidx<4+1; pidx++) {
            let finalScore = lastResult.scoreChangesPlusSticks[pidx]
            finalScore += pidx==4 ? GS.gs.prevRoundSticks*1000 : GS.gs.scores[pidx]
            cell = tr.insertCell()
            cell.textContent = `${finalScore}`
        }
        this.infoRoundModal.addEventListener('click', (event) => {
            this.infoRoundModal.close()
        })
    }
}
function createElemWithText(type, text) {
    let e = document.createElement(type)
    e.append(text)
    return e
}
function createParaElem(text) {
    return createElemWithText("p", text)
}
function createRect(x, width, totHeight, fillRatio, fill) {
    let y = (1-fillRatio)*totHeight
    let rect = document.createElementNS("http://www.w3.org/2000/svg", "rect")
    rect.setAttribute("x", x)
    rect.setAttribute("y", y)
    rect.setAttribute("width", width)
    rect.setAttribute("height", totHeight*fillRatio)
    rect.setAttribute("fill", fill)
    return rect
}
function createSvgText(x, y, text) {
    let svg = document.createElementNS("http://www.w3.org/2000/svg", "text")
    svg.setAttribute("x", x)
    svg.setAttribute("y", y)
    svg.setAttribute("fill", GS.C_colorText)
    svg.textContent = text
    return svg
}
function relativeToHero(pidx) {
    let relIdx = pidx<4 ? (4 + GS.heroPidx - pidx) % 4 : pidx
    return relIdx
}
function relativeToHeroStr(pidx, English=0) {
    let relIdx = relativeToHero(pidx)
    let key = ['Hero', 'Kami', 'Toimen', 'Shimo', 'Pot'][relIdx]
    if (English) {
        return key
    }
    return i18next.t(`position-rel.${key}`)
}
function sum(a) {
    return a.reduce((a,b)=>a+b,0)
}
function addTableRow(table, values){
    let tr = table.insertRow()
    for (let v of values) {
        let cell = tr.insertCell()
        if (typeof v == 'object') {
            cell.appendChild(v)
        } else {
            cell.innerHTML = v
        }
    }
}
class Tile {
    constructor(tile) {
        this.tile = tile
        this.tsumogiri = false
        this.riichi = false
        this.rotate = false
        this.called = false
    }
}

//take '2m' and return 2 + 10 etc.
function tm2t(str) { 
    if (str == undefined) {
        console.log('undefined!')
    }
    if (!isNaN(str)) {
        // console.log('already?', str)
        return str
    }
    //tenhou's tile encoding:
    //   11-19    - 1-9 man
    //   21-29    - 1-9 pin
    //   31-39    - 1-9 sou
    //   41-47    - ESWN WGR
    //   51,52,53 - aka 5 man, pin, sou
    const tcon = { m : 1, p : 2, s : 3, z : 4 };
    // handle mortal '5sr' for red 5s
    if (str.length==3) {
        if (str[0] != '5' || str[2] != 'r') {
            throw new Error('Expected something like "5sr"!')
        }
        str = str.substring(0, str.length - 1)
        return 50+tcon[str[1]]
    }
    let num = parseInt(str[0]);
    if (isNaN(num)) {
        //                                                   Pai=White Fa=Green Chun=Red
        const yakuhai = { 'e': 41, 's': 42, 'w': 43, 'n': 44, 'p':45, 'f':46, 'c': 47}
        let tile = yakuhai[str[0].toLowerCase()]
        if (tile == null) {
            throw new Error(`Could not parse ${str}`)
        }
        return tile
    }

    return num ? 10 * tcon[str[1]] + num : 50 + tcon[str[1]];
}

// take 2+10 and return '2m'
function tenhou2str(tileInt) {
    if (tileInt > 50) {
        const akacon = { 51:'0m', 52:'0p', 53:'0s'}
        return akacon[tileInt]
    }
    let suitInt = Math.floor(tileInt / 10)
    tileInt = tileInt % 10
    const tcon = ['m', 'p', 's', 'z']
    let output = tileInt.toString() + tcon[suitInt-1]
    return output
}

function tenhou2strH(tileInt) {
    let output = tenhou2str(tileInt)
    if (tileInt >= 41 && tileInt <= 47) {
        output = i18next.t(output)
    }
    return output
}

function tenhou2strShort(tileInt) {
    if (tileInt >= 41 && tileInt <= 47) {
        return i18next.t(tenhou2str(tileInt))
    }
    return tileInt % 10
}
// take 51 (0m) and return 15.1 for sorting
function tileInt2Float(tileInt) {
    let f = tileInt == 51 ? 15.1 : tileInt == 52 ? 25.1 : tileInt == 53 ? 35.1 : tileInt
    return f
}

// sort aka red fives
function tileSort(a, b) {
    let a1 = tileInt2Float(a)
    let b1 = tileInt2Float(b)
    return a1-b1
}

function normRedFive(t) {
    return t<51? t : t == 51 ? 15 : t == 52 ? 25 : t == 53 ? 35 : null
}

// 15 == 51, 25 == 52 (aka 5s are equal to normal 5s)
function fuzzyCompareTile(t1, t2) {
    let ft1 = normRedFive(t1)
    let ft2 = normRedFive(t2)
    return ft1 == ft2
}

function removeFromArray(array, value) {
    const indexToRemove = array.indexOf(value)
    if (indexToRemove === -1) { 
        throw new Error(`Value ${value} not in array ${array}`)
    }
    array.splice(indexToRemove, 1)
}

function onlyUpdateState() {
    GS.gs = new GameState(GS.fullData.split_logs[GS.hand_counter].log[0])
    for (let ply=0; ply <= GS.ply_counter; ply++) {
        let event = GS.ge[GS.hand_counter][ply]
        if (event.dora_marker) {
            GS.gs.thisRoundExtraDoras++
        }
        if (event.type == 'tsumo') {
            GS.gs.drawnTile[event.actor] = event.pai
            GS.gs.tilesLeft--
        } else if (event.type == 'chi' || event.type == 'pon' || event.type == 'daiminkan') {
            let dp = GS.gs.discardPond[event.target]
            dp[dp.length-1].called = true
            GS.gs.hands[event.actor].push(event.pai)
            let newCall = []
            let fromIdxRel = (4 + event.actor - event.target - 1) % 4
            let consumed = [...event.consumed]
            consumed.splice(fromIdxRel, 0, event.pai)
            for (let i=0; i<consumed.length; i++) {
                removeFromArray(GS.gs.hands[event.actor], consumed[i])
                newCall.push(consumed[i])
                if (i==fromIdxRel) {
                    newCall.push('rotate')
                }
                if (fromIdxRel+1 == i && event.type == 'daiminkan') {
                    newCall.push('rotate')
                    newCall.push('float')
                }
            }
            GS.gs.calls[event.actor] = newCall.concat(GS.gs.calls[event.actor])
        } else if (event.type == 'kakan') { // added kan
            GS.gs.hands[event.actor].push(GS.gs.drawnTile[event.actor])
            GS.gs.drawnTile[event.actor] = null
            removeFromArray(GS.gs.hands[event.actor], event.pai)
            let rotatedIdx = null
            for (let i=1; i<GS.gs.calls[event.actor].length; i++) {
                if (GS.gs.calls[event.actor][i]=='rotate' && fuzzyCompareTile(GS.gs.calls[event.actor][i-1], event.pai)) {
                    rotatedIdx = i
                    break
                }
            }
            if (rotatedIdx === null) {
                console.log(event, GS.gs.calls[event.actor])
                throw new Error('Cannot find meld to kakan to')
            }
            GS.gs.calls[event.actor].splice(rotatedIdx+1, 0, event.pai, 'rotate', 'float')
        } else if (event.type == 'ankan') { // closed kan
            GS.gs.hands[event.actor].push(GS.gs.drawnTile[event.actor])
            GS.gs.drawnTile[event.actor] = null
            let newCall = []
            for (let i=0; i<event.consumed.length; i++) {
                removeFromArray(GS.gs.hands[event.actor], event.consumed[i])
                if (i==0 || i==3) {
                    newCall.push('back')
                } else {
                    newCall.push(event.consumed[i])
                    newCall.push('rotate')
                    if (i==2) {
                        newCall.push('float')
                    }
                }
            }
            GS.gs.calls[event.actor] = newCall.concat(GS.gs.calls[event.actor])
        } else if (event.type == 'dahai') {
            // for calls there will not be a drawnTile
            if (GS.gs.drawnTile[event.actor]) {
                GS.gs.hands[event.actor].push(GS.gs.drawnTile[event.actor])
                GS.gs.drawnTile[event.actor] = null
            }
            let tile = new Tile(event.pai)
            tile.riichi = GS.ge[GS.hand_counter][ply-1].type == "reach"
            tile.tsumogiri = event.tsumogiri
            GS.gs.discardPond[event.actor].push(tile)
            removeFromArray(GS.gs.hands[event.actor], event.pai)
        } else if (event.type == 'reach') {
            // console.log('reach', GS.ply_counter)
        } else if (event.type == 'reach_accepted') {
            GS.gs.thisRoundSticks[event.actor]++
        } else if (event.type == 'hora' || event.type == 'ryukyoku') {
            GS.gs.handOver = true
        } else {
            console.log(event)
            throw new Error('unknown type')
        }
    }
    for (const hand of GS.gs.hands) {
        hand.sort(tileSort)
    }
}
function updateState() {
    onlyUpdateState()
    GS.ui.reset()
    GS.ui.updateHandInfo()
    GS.ui.updateDiscardPond()
    GS.ui.updateGridInfo()
    try { paintNav() } catch (e) { console.warn('nav', e) }
    try { renderRating(); renderCoach() } catch (e) { console.warn('coach panel', e) }
    // discardOverflowTest()
}

const waitType = {
    ryanmen:0,
    kanchan:1,
    penchan:2,
    tanki:3,
    shanpon:4
}
Object.freeze(waitType)
function generateWaits() {
    let waitsArray = []
    for (let ryanmen of [[2,3],[3,4],[4,5],[5,6],[6,7],[7,8]]) {
        for (let suit=1; suit<=3; suit++) {
            let wait = {}
            wait.tiles = [suit*10+ryanmen[0], suit*10+ryanmen[1]]
            wait.waitsOn = [suit*10+ryanmen[0]-1, suit*10+ryanmen[1]+1]
            wait.type = waitType.ryanmen
            waitsArray.push(wait)
        }
    }
    for (let kanchan of [[1,3],[2,4],[3,5],[4,6],[5,7],[6,8],[7,9]]) {
        for (let suit=1; suit<=3; suit++) {
            let wait = {}
            wait.tiles = [suit*10+kanchan[0], suit*10+kanchan[1]]
            wait.waitsOn = [suit*10+kanchan[0]+1]
            wait.type = waitType.kanchan
            waitsArray.push(wait)
        }
    }
    // Beware this is getting a little more ad-hoc...
    for (let penchan of [[1,2,3],[8,9,7]]) {
        for (let suit=1; suit<=3; suit++) {
            let wait = {}
            wait.tiles = [suit*10+penchan[0], suit*10+penchan[1]]
            wait.waitsOn = [suit*10+penchan[2]]
            wait.type = waitType.penchan
            waitsArray.push(wait)
        }
    }
    for (let tankiShanpon of ([1,2,3,4,5,6,7,8,9])) {
        for (let type of [waitType.tanki, waitType.shanpon]) {
            for (let suit=1; suit<=4; suit++) {
                if (suit==4 && tankiShanpon>7) {
                    continue // honors are 41-47 only
                }
                let wait = {}
                wait.type = type
                wait.tiles = Array(type==waitType.tanki ? 1:2).fill(suit*10+tankiShanpon)
                wait.waitsOn = [suit*10+tankiShanpon]
                waitsArray.push(wait)
            }
        }
    }
    return waitsArray
}

function calcCombos(waitsArray, genbutsu, discardsToRiichi, heroUnseenTiles, dora) {
    let discardsToRiichiNormRedFive = discardsToRiichi.map(normRedFive)
    let combos = {'all':0}
    let riichiTile = discardsToRiichiNormRedFive.slice(-1)[0]
    for (let wait of waitsArray) {
        let thisGenbutsu = wait.waitsOn.reduce((accum,t) => accum || genbutsu.has(t), false)
        if (thisGenbutsu) {
            continue
        }
        let involvedTiles = [...wait.tiles, ...wait.waitsOn]
        wait.combos = 1
        wait.numUnseen = []
        for (let [i,t] of wait.tiles.entries()) {
            if (i>0 && wait.type==waitType.shanpon) {
                wait.combos *= heroUnseenTiles[t]-1 // Shanpons pull the same tile, so after the first one there is 1 less remaining
                wait.numUnseen.push(heroUnseenTiles[t]-1)
            } else {
                wait.combos *= heroUnseenTiles[t]
                wait.numUnseen.push(heroUnseenTiles[t])
            }
        }
        if (wait.type == waitType.shanpon) {
            // Shanpons: Order doesn't matter. Technically Math.exp(length) but it's always 2 for this case
            wait.combos /= wait.tiles.length 
        }
        // wait.origCombos = wait.combos
        // heuristic adjustment for waits that players tend to aim for
        let honorTankiShanpon = [waitType.shanpon, waitType.tanki].includes(wait.type) && wait.tiles[0] > 40
        let nonHonorTankiShanpon = [waitType.shanpon, waitType.tanki].includes(wait.type) && wait.tiles[0] < 40
        if (waitType.ryanmen == wait.type) {
            let uraSuji = false
            let matagiSujiEarly = false
            let matagiSujiRiichi = false
            for (let discard of discardsToRiichiNormRedFive) {
                if (wait.tiles.includes(discard)) { continue }
                for (let waitTile of wait.tiles) {
                    if (discard%10 >= 4 && discard%10 <= 6 && Math.abs(discard-waitTile) == 2) {
                        uraSuji = true
                        break
                    }
                }
            }
            for (let discard of discardsToRiichiNormRedFive) {
                if (wait.tiles.includes(discard)) {
                    if (discard == riichiTile) {
                        matagiSujiRiichi = true
                    } else {
                        matagiSujiEarly = true
                    }
                }
            }
            wait.combos *= GS.C_ccw_ryanmen
            if (uraSuji) { wait.combos *= GS.C_ccw_uraSuji }
            if (matagiSujiEarly) { wait.combos *= GS.C_ccw_matagiSujiEarly}
            if (matagiSujiRiichi) { wait.combos *= GS.C_ccw_matagiSujiRiichi}
        } else if (honorTankiShanpon) {
            wait.combos *= GS.C_ccw_honorTankiShanpon
        } else if (nonHonorTankiShanpon) {
            wait.combos *= GS.C_ccw_nonHonorTankiShanpon
        } else if (waitType.kanchan == wait.type) {
            if (riichiTile%10>=4 && riichiTile%10<=6 && Math.abs(wait.waitsOn[0]-riichiTile)==3) {
                wait.combos *= GS.C_ccw_kanchanRiichiSujiTrap
            } else {
                wait.combos *= GS.C_ccw_kanchan
            }
        }

        let doraInvolved = false
        for (let tile of involvedTiles) {
            if (tile == dora) {
                doraInvolved = true
                break
            }
        }
        if (doraInvolved) {
            wait.combos *= GS.C_ccw_doraGreed
        }

        let akaInvolved = false
        for (let discard of discardsToRiichi) {
            if (discard > 50) {
                let normedDiscard = normRedFive(discard)
                for (let tile of involvedTiles) {
                    if (tile == normedDiscard) {
                        akaInvolved = true
                        break
                    }
                }
            }
        }
        if (akaInvolved) {
            wait.combos *= GS.C_ccw_akaDiscard
        }

        combos['all'] += wait.combos
        if (wait.type==waitType.shanpon) {
            wait.combos *= 2 // Shanpons always have a partner pair, so multiply by 2 *after* adding the the 'all' combos denominator
        }
        for (let t of wait.waitsOn) {
            if (!combos[t]) { combos[t]={'all':0, 'types':[]} }
            combos[t]['all'] += wait.combos
            combos[t]['types'].push(wait)
        }
    }
    return combos
}
function doraIndicator2dora(doraIndicator) {
    doraIndicator = normRedFive(doraIndicator)
    if (doraIndicator%10 == 9) {
        return doraIndicator-8
    }
    if (doraIndicator == 44) {
        return 41
    }
    if (doraIndicator == 47) {
        return 45
    }
    return doraIndicator+1
}
function combo2strAndP(key, combos) {
    let keyCombo = combos[key]
    let k = `${String(tenhou2strH(key)).padStart(2)}`
    if (!(key in combos)) {
        return [`${k}:`, 0]
    }
    let prob = keyCombo['all']/combos['all']
    let p = `${String((prob*100).toFixed(1)).padStart(4)}`
    let str = ''
    str += `${k}: ${p}%`
    let str_all_combos = ''
    for (let type of keyCombo.types) {
        str_all_combos += ' '
        str_all_combos += type.tiles.map(x => tenhou2strShort(x)).join('')
        str_all_combos += ':'+type.numUnseen.join('*')
        str_all_combos += ` ${(type.combos/combos['all']*100).toFixed(1)}%`
    }
    str += str_all_combos
    return [str, prob]
}
function showSujis(genbutsu) {
    let tables = []
    for (let suit=1; suit<=3; suit++) {
        tables[suit-1] = []
        for (let ta of [[1,2,3], [4,5,6], [7,8,9]]) {
            let row = []
            for (let t of ta) {
                let tile = createTile(tenhou2str(suit*10+t))
                row.push(tile)
                if (genbutsu.has(suit*10+t)) {
                    tile.classList.add('called')
                }
            }
            tables[suit-1].push(row)
        }
    }
    let sujiCnt = 18
    for (let t of [4,5,6]) {
        for (let suit=1; suit<=3; suit++) {
            (genbutsu.has(suit*10+t) || genbutsu.has(suit*10+t-3)) && sujiCnt--
            (genbutsu.has(suit*10+t) || genbutsu.has(suit*10+t+3)) && sujiCnt--
        }
    }
    return [sujiCnt, tables]
}

// For now just return true if they called riichi
// Maybe could also do it for people who called twice?
// Or called dora pon?
function tenpaiEstimate(pidx) {
    return GS.gs.thisRoundSticks[pidx]
}

function initUnseenTiles(pidx, gs) {
    let allTiles = [11,12,13,14,15,16,17,18,19,21,22,23,24,25,26,27,28,29,31,32,33,34,35,36,37,38,39,41,42,43,44,45,46,47]
    let numT = {}
    for (let t of allTiles) {
        numT[t] = 4
    }
    let seenTiles = []
    seenTiles.push(...gs.hands[pidx])
    seenTiles.push(gs.doraIndicator[0])
    for (let t of seenTiles) {
        numT[normRedFive(t)]--
    }
    return numT
}

function weseeitnow(gs, tile, pidxAlreadySaw) {
    for (let pidx=0; pidx<4; pidx++) {
        if (pidx==pidxAlreadySaw) {
            continue
        }
        gs.unseenTiles[pidx][normRedFive(tile)]--
    }
}
function incrementalCalcDangerHelper(event, prevEvent, gs) {
    // process dahai and kakans the turn after they happen
    if (!prevEvent) {
        // do nothing if it's null
    } else if (prevEvent.type == 'kakan') {
        weseeitnow(gs, prevEvent.pai, prevEvent.actor)
        for (let pidx=0; pidx<4; pidx++) {
            // genbutsu if reach_accepted player doesn't Rob the Kan
            if (gs.reach_accepted[pidx]) {
                gs.genbutsu[pidx].add(normRedFive(prevEvent.pai))
            }
        }
    } else if (prevEvent.type == 'dahai') { // discard
        weseeitnow(gs, normRedFive(prevEvent.pai), prevEvent.actor)
        for (let pidx=0; pidx<4; pidx++) {
            /// genbutsu = we discarded it ourselves, or we reach_accepted and anyone discarded it
            if (prevEvent.actor == pidx || gs.reach_accepted[pidx]) {
                gs.genbutsu[pidx].add(normRedFive(prevEvent.pai))
            }
            if (prevEvent.actor == pidx && !gs.reach_accepted[pidx]) {
                gs.discardsToRiichi[pidx].push(prevEvent.pai)
            }
        }
    }

    // other events on the turn they happen
    if (event.dora_marker) {
        weseeitnow(gs, normRedFive(event.dora_marker), -1)
    }
    if (event.type == 'tsumo') { // draw
        gs.unseenTiles[event.actor][normRedFive(event.pai)]--
    } else if (['chi', 'pon', 'daiminkan', 'ankan'].includes(event.type)) {
        // the other players will see the consumed tiles
        for (let tile of event.consumed) {
            weseeitnow(gs, normRedFive(tile), event.actor)
        }
    } else if (event.type == 'reach_accepted') {
        gs.reach_accepted[event.actor] = true
    }
}
function doCalculateUkeire(finalHand, finalCalls, thisUnseenTiles) {
    let ukeireHand = Array(38).fill(0)
    for (let t of finalHand) {
        ukeireHand[normRedFive(t)-10]++
    }
    // For now we are only dealing with Riichi, so the only calls possible are ankans
    let ankans = new Set(finalCalls.filter(x => !isNaN(x)))
    for (const t of ankans) {
        ukeireHand[normRedFive(t)-10] += 3
    }
    let ukerieUnseen = []
    for (let i=0; i<38; i++) {
        ukerieUnseen[i] = i%10==0 ? 0 : thisUnseenTiles[i+10]
    }
    let ukeire = calculateUkeire(ukeireHand, ukerieUnseen, calculateMinimumShanten)
    return ukeire
}
function showDangers(thisPidx, tenpaiPidx, thisUnseenTiles, genbutsu, discardsToRiichi, event, dora, dangersDiv) {
    let combos = calcCombos(generateWaits(), genbutsu, discardsToRiichi, thisUnseenTiles, dora)
    dangersDiv.append(createElemWithText('p', i18next.t('Pusher') + ': ' + relativeToHeroStr(thisPidx)))
    dangersDiv.append(createElemWithText('p', i18next.t('Tenpai') + ': ' + relativeToHeroStr(tenpaiPidx)))
    dangersDiv.append(createElemWithText('pre', ' '))

    let [sujiCnt, sujiTables] = showSujis(genbutsu)
    dangersDiv.append(createElemWithText('p', `${i18next.t('sujis-tested')} ${18-sujiCnt}/18 (${i18next.t('suji-dealin-rate')} 1/${sujiCnt} = ${(1/sujiCnt*100).toFixed(1)}%)`))
    let span
    span = document.createElement("span")
    dangersDiv.append(span)
    span.style.display = "inline-block"
    for (let table of sujiTables) {
        let tableElem = document.createElement("table")
        span.append(tableElem)
        tableElem.style.display = "inline-block"
        tableElem.style.margin = "10px"
        for (let row of table) {
            addTableRow(tableElem, row)
        }
    }
    dangersDiv.append(createElemWithText('pre', ' '))

    dangersDiv.append(createElemWithText('p', `${i18next.t('Tile dealin rates')}`))
    span = document.createElement("span")
    dangersDiv.append(span)
    span.style.display = "inline-block"
    let tables = []
    for (let i=0; i<4; i++) {
        tables[i] = document.createElement("table")
        span.append(tables[i])
        tables[i].classList.add('hover-rows')
        tables[i].classList.add('wider-table')
        tables[i].style.display = "inline-block"
        tables[i].style.verticalAlign = "top"
        tables[i].style.margin = "10px"
    }
    let dangersDetailDiv = document.createElement("div")
    dangersDiv.append(dangersDetailDiv)
    for (let tile=11; tile<=47; tile++) {
        if (tile%10==0) { 
            continue
        }
        let suit = Math.floor(tile/10)
        let tileDiv = createTile(tenhou2str(tile)).innerHTML
        let k = `${String(tenhou2strH(tile))}`
        let probStr = '-'
        if (tile in combos) {
            let prob = combos[tile]['all']/combos['all']
            probStr = `${String((prob*100).toFixed(1))}`
        }
        addTableRow(tables[suit-1], [tileDiv,probStr])
        if (tile in combos) {
            tables[suit-1].lastChild.lastChild.addEventListener('click', (event) => {
                showDangersDetail(tile, combos, dangersDetailDiv)
            })
        }
    }
    dangersDiv.append(createElemWithText('pre', ' '))
    dangersDiv.append(createElemWithText('pre', ' '))
}
function showDangersDetail(keyTile, combos, dangersDetailDiv) {
    let table = document.createElement("table")
    table.classList.add('wider-table')
    let span = document.createElement('span')
    let tileDiv = createTile(tenhou2str(keyTile))
    span.innerHTML = tileDiv.innerHTML + ' ' + i18next.t('Details')
    dangersDetailDiv.replaceChildren(span)
    dangersDetailDiv.append(table)
    let keyCombo = combos[keyTile]
    let numRows = 0
    addTableRow(table, [i18next.t("Wait type"), i18next.t("Tiles"), i18next.t("Left"), "%"])
    table.lastChild.lastChild.style.borderBottom = `1px solid ${GS.C_colorText}`;
    for (let wait of keyCombo.types) {
        numRows++
        let row = []
        row.push(i18next.t(`waitTypeStr`, {returnObjects:true})[wait.type])
        row.push(wait.tiles.map(x => createTile(tenhou2str(x)).innerHTML).join(''))
        row.push(wait.numUnseen.join('*'))
        row.push(`${(wait.combos/combos['all']*100).toFixed(1)}`)
        addTableRow(table, row)
    }
    table.lastChild.lastChild.style.borderBottom = `1px solid ${GS.C_colorText}`;
    addTableRow(table, [i18next.t("Total %"), "", "", `${(keyCombo['all']/combos['all']*100).toFixed(1)}`])
    table = document.createElement("table")
    dangersDetailDiv.append(table)
    table.style.visibility = 'hidden'
    for (let i=0; i<5-numRows; i++) {
        addTableRow(table, ['-'])
    }
}
function testDangers() {
    // Pretend we don't see any tiles.
    GS.ui.genericModalBody.append(createElemWithText('pre', ('wait pattern combos:')))
    let sumP = 0
    let allTiles = [11,12,13,14,15,16,17,18,19,21,22,23,24,25,26,27,28,29,31,32,33,34,35,36,37,38,39,41,42,43,44,45,46,47]
    let numT = {}
    for (let t of allTiles) {
        numT[t] = 4
    }
    numT[47] = 1 // Test only 1 unseed Red dragon
    // riichi suji trap test
    // let combos = calcCombos(generateWaits(), [15,25,16,26,36], [25,16,26,36,15], numT, 46)
    // mostly flat test
    let combos = calcCombos(generateWaits(), [], [], numT, 46)
    for (let [key,combo] of Object.entries(combos)) {
        if (key=='all') {
            continue
        }
        sumP += combos[key]['all']
        GS.ui.genericModalBody.append(createElemWithText('pre', (combo2strAndP(key,combos))[0]))
    }
    GS.ui.genericModalBody.append(createElemWithText('pre', (`sumP ${String((sumP/combos['all']*100).toFixed(1)).padStart(4)}%`)))
}
function calcDanger() {
    console.time('calcDanger')
    let saveHand = GS.hand_counter
    let savePly = GS.ply_counter
    for (GS.hand_counter=0; GS.hand_counter < GS.ge.length; GS.hand_counter++) {
        GS.ply_counter = GS.ge[GS.hand_counter].length-1
        onlyUpdateState()
        let finalHands = GS.gs.hands // Beware: For now don't need a deep copy...
        let finalCalls = GS.gs.calls // Beware: For now don't need a deep copy...
        for (let ply=0; ply < GS.ge[GS.hand_counter].length; ply++) {
            let event = GS.ge[GS.hand_counter][ply]
            let prevEvent = GS.ge[GS.hand_counter][ply-1]
            let nextEvent = GS.ge[GS.hand_counter][ply+1]
            let gs = GS.gs
            incrementalCalcDangerHelper(event, prevEvent, gs)
            for (let tenpaiPidx=0; tenpaiPidx<4; tenpaiPidx++) {
                if (!gs.reach_accepted[tenpaiPidx] || event.actor === undefined) {
                    continue // skip non-tenpai players, and e.g. ryukyoku
                }
                for (let thisPidx=0; thisPidx<4; thisPidx++) {
                    let dangerousEvent = (event.type == 'dahai' || event.type=='kakan') && 
                                        event.actor != tenpaiPidx && event.actor == thisPidx
                    let tsumoAttempt = event.actor == tenpaiPidx && event.type == 'tsumo'
                    let thisUnseenTiles = gs.unseenTiles[thisPidx]
                    if (tsumoAttempt) {
                        let numUnseenTiles = sum(Object.values(thisUnseenTiles))
                        let ukeire = doCalculateUkeire(finalHands[tenpaiPidx], finalCalls[tenpaiPidx], thisUnseenTiles)
                        let success = nextEvent.type == 'hora'
                        event['tsumoAttempt'] = [success, ukeire['value'], numUnseenTiles]
                    }
                    if (thisPidx != GS.heroPidx && thisPidx != event.actor) {
                        continue
                    }
                    let thisDanger = {}
                    thisDanger['dangerousEvent'] = dangerousEvent
                    thisDanger['combos'] = calcCombos(generateWaits(), gs.genbutsu[tenpaiPidx], gs.discardsToRiichi[tenpaiPidx], thisUnseenTiles, gs.dora[0])
                    thisDanger['unseenTiles'] = {...thisUnseenTiles}
                    thisDanger['genbutsu'] = new Set(gs.genbutsu[tenpaiPidx])
                    thisDanger['discardsToRiichi'] = [...gs.discardsToRiichi[tenpaiPidx]]
                    thisDanger['event'] = event
                    thisDanger['ply'] = ply
                    thisDanger['dora'] = gs.dora[0]
                    if (!('danger' in event)) { event['danger'] = [[],[],[],[]]}
                    event['danger'][tenpaiPidx][thisPidx] = thisDanger
                }
            }

        }
    }
    GS.hand_counter = saveHand
    GS.ply_counter = savePly
    console.timeEnd('calcDanger')
}
function showDangerDetail() {
    GS.ui.genericModal.style.marginRight = '0px'
    GS.ui.genericModalBody.replaceChildren()
    GS.ui.genericModal.querySelector(".title").textContent = i18next.t("dealin-rate")
    const dangersDiv = document.createElement('div')
    GS.ui.genericModalBody.append(dangersDiv)
    let event = GS.ge[GS.hand_counter][GS.ply_counter]
    let foundone = false
    for (let tenpaiPidx=0; tenpaiPidx<4; tenpaiPidx++) {
        if (tenpaiPidx == event.actor || !event.danger || !event.danger[tenpaiPidx] || !event.danger[tenpaiPidx][event.actor]) {
            continue
        }
        foundone = true
        let d = event.danger[tenpaiPidx][event.actor]
        showDangers(event.actor, tenpaiPidx, d['unseenTiles'], d['genbutsu'], d['discardsToRiichi'], d['event'], d['dora'], dangersDiv)
    }
    if (foundone) {
        showModalAndWait(GS.ui.genericModal)
    } else {
        console.log('No danger')
    }
}

function showDangerTable() {
    GS.ui.genericModal.style.marginRight = '0px'
    GS.ui.genericModalBody.replaceChildren()
    GS.ui.genericModal.querySelector(".title").textContent = i18next.t("accum-dealin-rate")
    let resultTypeStr = GS.ui.getResultTypeStr()
    GS.ui.genericModalBody.append(createElemWithText('p', i18next.t('Final Result:')))
    for (let s of resultTypeStr) {
        GS.ui.genericModalBody.append(createElemWithText('p', s))
    }
    const dangersDiv = document.createElement('div')
    let table = document.createElement("table")
    table.classList.add('wider-table')
    table.classList.add('hover-rows')
    GS.ui.genericModalBody.append(table)
    addTableRow(table, [i18next.t('Pusher'), i18next.t('Tile'), i18next.t('Tenpai'), '%', i18next.t('Total %')])
    for (let thisPidx=0; thisPidx<4; thisPidx++) {
        let accumP = 0
        let firstRow = true
        for (let event of GS.ge[GS.hand_counter]) {
            let firstTenpai = true
            if ('danger' in event && event['danger'][thisPidx]) {
                for (let tenpaiPidx=0; tenpaiPidx<4; tenpaiPidx++) {
                    if (event['danger'][tenpaiPidx][thisPidx] && event['danger'][tenpaiPidx][thisPidx]['dangerousEvent']) {
                        let d = event['danger'][tenpaiPidx][thisPidx]
                        let tile = normRedFive(event.pai)
                        let p = (tile in d['combos']) ? d['combos'][tile]['all']/d['combos']['all'] : 0
                        accumP = accumP + (1-accumP)*p
                        let row = [relativeToHeroStr(thisPidx), createTile(tenhou2str(d['event'].pai)), relativeToHeroStr(tenpaiPidx), (p*100).toFixed(1), (accumP*100).toFixed(1)]
                        if (!firstTenpai) {
                            row[1] = '' // Don't repeat the tile
                            firstTenpai = false
                        }
                        firstTenpai = false
                        if (!firstRow) {
                            row[0] = '' // Don't repeat thisPidx
                        }
                        addTableRow(table, row)
                        if (firstRow) {
                            table.lastChild.lastChild.style.borderTop = `1px solid ${GS.C_colorText}`;
                            firstRow = false
                        }
                        table.lastChild.lastChild.addEventListener('click', (event) => {
                            GS.ply_counter = d['ply']-1
                            updateState()
                        })
                    }
                }
            }
            continue
        }
    }
    GS.ui.genericModalBody.append(createElemWithText('pre', ' '))
    table = document.createElement("table")
    GS.ui.genericModalBody.append(table)
    addTableRow(table, [i18next.t('Tenpai'), i18next.t('Tsumo'), '%', i18next.t('Total %')])
    for (let pidx=0; pidx<4; pidx++) {
        let accumP = 0
        let firstRow = true
        let who = relativeToHeroStr(pidx)
        for (let event of GS.ge[GS.hand_counter]) {
            if (event.actor == pidx && 'tsumoAttempt' in event) {
                let ta = event['tsumoAttempt']
                let p = ta[1]/ta[2]
                accumP = accumP + (1-accumP)*p
                let result = ta[0] ? i18next.t('hit') : i18next.t('miss')
                addTableRow(table, [who, result, (p*100).toFixed(1), (accumP*100).toFixed(1)])
                if (firstRow) {
                    table.lastChild.lastChild.style.borderTop = `1px solid ${GS.C_colorText}`;
                    firstRow = false
                }
            }
        }
    }
    GS.ui.genericModalBody.append(dangersDiv)
    // testDangers()
    showModalAndWait(GS.ui.genericModal)
}

function addResult() {
    for (let [idx, currGeList] of GS.ge.entries()) {
        let gs = new GameState(GS.fullData.split_logs[idx].log[0])
        // TODO: Currently using the tenhou split_logs to parse result
        // And assuming there is only one hora event. Remove the extras (double/triple Ron)
        while(currGeList.slice(-2)[0].type == 'hora') {
            currGeList.splice(-2, 1)
        }
        let result = currGeList.slice(-1)[0]
        for (let tmpPly=0; tmpPly<currGeList.length; tmpPly++) {
            let fourRiichiDraw = sum(gs.thisRoundSticks) == 3 && currGeList[tmpPly].type == "ryukyoku" && currGeList[tmpPly-2].type == 'reach'
            if (fourRiichiDraw) {
                gs.thisRoundSticks[currGeList[tmpPly-2].actor]++
            } else if (currGeList[tmpPly].type == "reach_accepted") {
                gs.thisRoundSticks[currGeList[tmpPly].actor]++
            }
        }
        result.scoreChangesPlusSticks = gs.scoreChanges.concat([0])
        for (let pidx=0; pidx<4; pidx++) {
            result.scoreChangesPlusSticks[pidx] -= gs.thisRoundSticks[pidx]*1000
        }
        if (gs.result == '和了') {
            // If there was a winner, they get the prevRoundSticks
            result.scoreChangesPlusSticks[4] = -gs.prevRoundSticks*1000
        } else {
            // If no winner, pot "wins" the sticks
            result.scoreChangesPlusSticks[4] += sum(gs.thisRoundSticks)*1000
        }
        console.assert(sum(result.scoreChangesPlusSticks)==0)
    }

}

function createTile(tileStr) {
    if (!tileStr || tileStr == null || tileStr.length>5) {
        console.log('error', tileStr)
        throw new Error()
    }
    const tileDiv = document.createElement('div')
    const tileImg = document.createElement('img')
    tileDiv.append(tileImg)
    tileDiv.classList.add('tileDiv')
    tileImg.src = `media/Regular_shortnames/${tileStr}.svg`
    tileImg.classList.add('tileImg')
    return tileDiv
}

// Input: 123m456s789p1112z Output: 1m2m3m4s5s6s7p8p9p1z1z1z2z
function convertTileStr(str) {
    let output = []
    let suit = ''
    // go backwards so we know what suit each number is
    for (i=str.length-1; i>=0; i--) {
        if (!isNaN(str[i])) {
            if (suit === '') {
                throw new Error(`error in convertTileStr: ${str}`)
            }
            output.push(str[i]+suit)
        } else {
            suit = str[i]
        }
    }
    output.reverse()
    return output
}

function incPlyCounter() {
    if (GS.ply_counter < GS.ge[GS.hand_counter].length-1) {
        GS.ply_counter++
    } else {
        incRoundCounter()
    }
}

function decPlyCounter() {
    if (GS.ply_counter > 0) {
        GS.ply_counter--
    } else {
        decRoundCounter()
        GS.ply_counter = GS.ge[GS.hand_counter].length-1
    }
}

function incRoundCounter() {
    GS.hand_counter++
    if (GS.hand_counter >= GS.ge.length) {
        GS.hand_counter = 0
    }
    GS.ply_counter = 0
}

function decRoundCounter() {
    GS.hand_counter--
    if (GS.hand_counter < 0) {
        GS.hand_counter = GS.ge.length-1
    }
    GS.ply_counter = GS.ge[GS.hand_counter].length-1
}

function stopCondition(onlyMismatches) {
    const evs = GS.ge[GS.hand_counter]
    let mortalEval = evs[GS.ply_counter].mortalEval
    const last = GS.ply_counter == evs.length - 1
    // 「上一/下一恶手」直接停在库里的手（门槛之上全部入库、全部有解读）
    if (onlyMismatches && COACH && COACH.moves) {
        const mv = COACH.moves[GS.hand_counter + ':' + GS.ply_counter]
        return !!mv || last
    }
    let mismatch = mortalEval && !mortalEval.is_equal && (mortalEval.details[mortalEval.actual_index].normProb < GS.errorThreshold)
    return mortalEval && (!onlyMismatches || mismatch) || last
}
function showModalAndWait(modal) {
    modal.showModal()
    modal.addEventListener('click', (event) => {
        if (event.target == modal) {
            modal.close()
        }
    })
}
function i18nElem(key) {
    const elem = document.getElementById(key)
    elem.innerHTML = i18next.t(key)
    return elem
}
function toggleDealinRate() {
    GS.showDealinRate = !GS.showDealinRate
    localStorage.setItem("showDealinRate", GS.showDealinRate ? 1 : 0)
    updateState()
}
function toggleErrorThreshold() {
    let saveET = GS.errorThreshold*100
    GS.errorThreshold = prompt(i18next.t("error-threshold-prompt", {current:`${(GS.errorThreshold*100).toFixed(0)}`}))
    if (GS.errorThreshold == null) {
        GS.errorThreshold = saveET
    }
    GS.errorThreshold = Number(GS.errorThreshold)
    if (isNaN(GS.errorThreshold) || GS.errorThreshold < 0 || GS.errorThreshold > 100) {
        GS.errorThreshold = saveET
    }
    GS.errorThreshold = GS.errorThreshold / 100
    localStorage.setItem("errorThreshold", GS.errorThreshold)
}
function connectUI() {
    // first part might run more than once when people change language
    document.title = i18next.t("title")
    const roundInc = i18nElem("round-inc")
    const roundDec = i18nElem("round-dec")
    const prevMismatch = i18nElem("prev-mismatch")
    const nextMismatch = i18nElem("next-mismatch")
    const inc2 = i18nElem("ply-inc2")
    const dec2 = i18nElem("ply-dec2")
    const inc = i18nElem("ply-inc")
    const dec = i18nElem("ply-dec")
    const options = i18nElem("options")
    const toggleShowHands =  i18nElem("toggle-hands")
    const toggleMortalAdvice = i18nElem("toggle-mortal-advice")
    const toggleDealinRateElem = i18nElem("toggle-dealin-rate")
    const toggleErrorThresholdElem = i18nElem("toggle-error-threshold")
    const about =  i18nElem("about")
    const aboutBody = [document.getElementById("about-body-0"), document.getElementById("about-body-1")]
    const langLabel = i18nElem("langLabel")
    const optionsLabel = i18nElem("options-label")
    let aboutBodyLists = [i18next.t("about-body-0", {returnObjects:true}), i18next.t("about-body-1", {returnObjects:true})]
    aboutBody[0].replaceChildren(document.createElement("ul"))
    for (let i=0; i<aboutBodyLists[0].length; i++) {
        let ul = document.createElement("li")
        let node = document.createElement("span")
        node.innerHTML = aboutBodyLists[0][i]
        ul.appendChild(node)
        aboutBody[0].appendChild(ul)
    }
    let table = document.createElement("table")
    aboutBody[1].replaceChildren(table)
    for (let i=0; i<aboutBodyLists[1].length; i++) {
        addTableRow(table, aboutBodyLists[1][i])
    }
    // only run the rest once ever
    if (GS.uiConnected) {
        return
    }
    GS.uiConnected = true
    const optionsModal = document.getElementById("options-modal")
    const closeOptionsModal = document.querySelector(".options-close")
    const aboutModal =  document.getElementById("about-modal")
    const infoRound = document.querySelector('.info-round')
    const infoRoundModal = document.querySelector('.info-round-modal')
    const closeModal = document.querySelector('.info-round-close')
    const closeAboutModal = document.querySelector('.about-close')
    const langSelect = document.getElementById("langSelect")
    const genericModalClose = document.getElementById('generic-modal-close')
    const genericModal = document.getElementById('generic-modal')
    const allModals = document.querySelectorAll('.modal')
    langSelect.value = i18next.language
    langSelect.addEventListener("change", () => {
        if (i18next.language == langSelect.value) {
            return
        }
        i18next.changeLanguage(langSelect.value)
        localStorage.setItem("lang", langSelect.value)
        connectUI()
        GS.ui.updateResultsTable()
        GS.ui.updateAbout()
        updateState()
    })
    inc.addEventListener("click", () => {
        incPlyCounter();
        updateState()
    });
    inc2.addEventListener("click", () => {
        do {
            incPlyCounter();
        } while (!stopCondition(false))
        updateState()
    });
    nextMismatch.addEventListener("click", () => {
        if (COACH && COACH.moves) { jumpBad(1); return }
        do {
            incPlyCounter();
        } while (!stopCondition(true))
        updateState()
    });
    dec.addEventListener("click", () => {
        decPlyCounter();
        updateState()
    });
    dec2.addEventListener("click", () => {
        do {
            decPlyCounter();
        } while (!stopCondition(false))
        updateState()
    });
    prevMismatch.addEventListener("click", () => {
        if (COACH && COACH.moves) { jumpBad(-1); return }
        do {
            decPlyCounter();
        } while (!stopCondition(true))
        updateState()
    });
    roundInc.addEventListener("click", () => {
        incRoundCounter();
        updateState()
    });
    roundDec.addEventListener("click", () => {
        decRoundCounter();
        updateState()
    });
    options.addEventListener('click', () => {
        showModalAndWait(optionsModal)
    })
    toggleShowHands.addEventListener("click", () => {
        GS.showHands = !GS.showHands
        updateState()
    })
    toggleMortalAdvice.addEventListener("click", () => {
        GS.showMortal = !GS.showMortal
        updateState()
    })
    toggleDealinRateElem.addEventListener("click", () => {
        toggleDealinRate()
    })
    toggleErrorThresholdElem.addEventListener("click", () => {
        toggleErrorThreshold()
    })
    about.addEventListener("click", () => {
        showModalAndWait(aboutModal)
    })
    infoRound.addEventListener("click", () => {
        infoRoundModal.showModal()
    })
    closeModal.addEventListener("click", () => {
        infoRoundModal.close()
    })
    genericModalClose.addEventListener("click", () => {
        genericModal.close()
    })
    closeAboutModal.addEventListener("click", () => {
        aboutModal.close()
    })
    closeOptionsModal.addEventListener("click", () => {
        optionsModal.close()
    })
    for (let pidx=1; pidx<4; pidx++) {
        document.querySelector(`.grid-hand-p${pidx}`).addEventListener("click", () => {
            GS.showHands = !GS.showHands
            updateState()
        })
    }
    document.querySelector('.discard-bars-svg').addEventListener("click", () => {
        GS.showMortal = !GS.showMortal
        updateState()
    })
    document.querySelector('.danger-bars-svg').addEventListener("click", () => {
        if (GS.showDealinRate) {
            showDangerDetail()
        }
    })
    document.addEventListener('keydown', function(event) {
        // If any modal is open, close the modal instead of doing anything else
        // But only on "normal" keys
        //   to avoid closing on e.g. shift or print screen for people doing screenshot hotkeys
        if (/^[a-z0-9]$/i.test(event.key) || ["Escape", " ", "Enter", "Backspace"].includes(event.key)) {
            for (let thisModal of allModals) {
                if (thisModal.open) {
                    thisModal.close()
                    return
                }
            }
        }
        if (event.key == 'h') {
            GS.showHands = !GS.showHands
            updateState()
        } else if (event.key == 'm') {
            GS.showMortal = !GS.showMortal
            updateState()
        } else if (event.key == 'PageUp' || event.key == ',') {
            do {
                decPlyCounter();
            } while (!stopCondition(true))
            updateState()
        } else if (event.key == 'PageDown' || event.key == '.') {
            do {
                incPlyCounter();
            } while (!stopCondition(true))
            updateState()
        } else if (event.key == 'Home') {
            if (GS.ply_counter != 0) {
                GS.ply_counter = 0
            } else {
                decRoundCounter()
            }
            updateState()
        } else if (event.key == 'End') {
            if (GS.ply_counter != GS.ge[GS.hand_counter].length-1) {
                GS.ply_counter = GS.ge[GS.hand_counter].length-1
            } else {
                incRoundCounter()
            }
            updateState()
        } else if (event.key == 'ArrowDown') {
            do {
                incPlyCounter();
            } while (!stopCondition(false))
            updateState()
        } else if (event.key == 'ArrowUp') {
            do {
                decPlyCounter();
            } while (!stopCondition(false))
            updateState()
        } else if (event.key == 'ArrowRight') {
            incPlyCounter()
            updateState()
        } else if (event.key == 'ArrowLeft') {
            decPlyCounter()
            updateState()
        } else if (event.key == 'd') {
            toggleDealinRate()
        } else if (event.key == 'e') {
            toggleErrorThreshold()
        } else if (event.key == 'a') {
            if (GS.showDealinRate) {
                showDangerTable()
            }
        } else if (event.key == 'z') {
            if (GS.showDealinRate) {
                showDangerDetail()
            }
        } else if (event.key == 'b') {
            const urlParams = new URLSearchParams(window.location.search)
            urlParams.set('hand', GS.hand_counter)
            urlParams.set('ply', GS.ply_counter)
            urlParams.set('showMortal', GS.showMortal ? 1 : 0)
            window.location.href = window.location.pathname + '?' + urlParams.toString()
        } else if (event.key == '?') {
            showModalAndWait(aboutModal)
        }
    });
    document.addEventListener('wheel', function(event) {
        // TODO: I think the modals themselves should block propogation of events instead?
        // If any modal is open, close the modal instead of doing anything else
        for (let thisModal of allModals) {
            if (thisModal.open) {
                // Except don't close the danger modal, since we may need to scroll it
                if (!([genericModal, aboutModal, infoRoundModal].includes(thisModal))) {
                    thisModal.close()
                }
                return
            }
        }
        if (event.deltaY > 0) {
            incPlyCounter()
            updateState()
        } else if (event.deltaY < 0) {
            decPlyCounter()
            updateState()
        } else {
            console.log('Error? deltaY=0?')
            console.log(event)
        }
    })
    // window.matchMedia(`(max-width: ${GS.mediaBreak})`).onchange = (event) => {
    //     GS.updateZoom()
    //     updateState()
    // }
    window.matchMedia("(orientation: portrait)").onchange = (event) => {
        GS.updateZoom()
        updateState()
    }
}

function mergeMortalEvals(data) {
    for (let [i, round] of GS.ge.entries()) {
        let currReviewKyoku = data.review.kyokus[i]
        let reviewIdx = 0
        for (let event of round) {
            let mortalEval = currReviewKyoku.entries[reviewIdx]
            if (mortalEval === undefined) {
                break // out of events to merge
            }
            let opponentTsumo = event.actor != GS.heroPidx && event.type=='tsumo'
            let heroDahai = event.actor == GS.heroPidx && event.type=='dahai'
            if (opponentTsumo || heroDahai) {
                continue
            }
            let heroRiichiDiscard = event.actor == GS.heroPidx && event.type == 'reach' && mortalEval.junme == currReviewKyoku.entries[reviewIdx-1].junme
            if (event.actor == mortalEval.last_actor && (event.pai == mortalEval.tile || heroRiichiDiscard)) {
                event.mortalEval = mortalEval
                reviewIdx++
            }
        }
        if (reviewIdx < currReviewKyoku.entries.length) {
            console.log("Didn't merge all events", round, currReviewKyoku.entries, reviewIdx)
            throw new Error()
        }
    }
}

function deepMap(obj, key, f) {
    const stack = [obj];
    while (stack.length > 0) {
        const current = stack.pop();
        if (typeof current === 'object') {
            for (let prop in current) {
                if (current.hasOwnProperty(prop)) {
                    if (prop === key) {
                        // console.log(prop, current[prop], f(current[prop]))
                        current[prop] = f(current[prop])
                    } else if (typeof current[prop] === 'object') {
                        stack.push(current[prop]);
                    }
                }
            }
        }
    }
}
function convertConsumed(data) {
    for (let i=0; i < data.length; i++) {
        data[i] = tm2t(data[i])
    }
    return data
}
function convertPai2Tenhou(data) {
    deepMap(data, 'pai', tm2t)
    deepMap(data, 'tile', tm2t)
    deepMap(data, 'dora_marker', tm2t)
    deepMap(data, 'consumed', convertConsumed)
}
function getBody(data) {
    const parser = new DOMParser()
    let body = parser.parseFromString(data, 'text/html').querySelector('body').textContent
    data = JSON.parse(body)
    return data
}
function parseMortalJsonStr(data) {
    GS.fullData = data
    GS.heroPidx = GS.fullData.player_id
    GS.ui.setPovPidx(GS.fullData.player_id)
    GS.ge = []
    let currGe = null
    for (let [idx, event] of data.mjai_log.entries()) {
        if (event.type == 'end_game' || event.type == 'start_game' || event.type == 'dora') {
            continue
        }
        if (event.type == 'start_kyoku') {
            currGe = []
            continue
        }
        if (event.type == 'end_kyoku') {
            GS.ge.push(currGe)
            currGe = null
            continue
        }
        if (data.mjai_log[idx-1].type == 'dora') {
            event.dora_marker = data.mjai_log[idx-1].dora_marker
        }
        currGe.push(event)
    }
    return data
}

function normalizeMortalEvals(data) {
    for (let kyoku of data.review.kyokus) {
        for (let mortalEval of kyoku.entries) {
            let probs = mortalEval.details.map(x => x.prob)
            // Use soft versions for the bars so that tiny probs are a little more visible
            // It's just visual so black magic is Ok here.
            let softNormProbs = normalizeAndSoften(probs, GS.C_soft_T)
            // Use normal version for calculating the actual error size
            // So that this metric is not black magic.
            let normProbs = normalizeAndSoften(probs, 1)
            mortalEval.details = mortalEval.details.map((obj, idx) => {
                return { ...obj, softNormProb: softNormProbs[idx]}
            })
            mortalEval.details = mortalEval.details.map((obj, idx) => {
                return { ...obj, normProb: normProbs[idx]}
            })
        }
    }
}

function setMortalJsonStr(data) {
    data = parseMortalJsonStr(data)
    convertPai2Tenhou(data)
    normalizeMortalEvals(data)
    mergeMortalEvals(data)
    calcDanger()
    addResult()
    GS.ui.updateResultsTable()
    GS.ui.updateAbout()
}

// Soften using temperature T
// Then normalize so the highest entry is set to 1, others scaled relative to the highest
function normalizeAndSoften(pdfs, T) {
    const hotter = pdfs.map(x => Math.pow(x, 1/T))
    const denom = Math.max(...hotter)
    return hotter.map(x => x/denom)
}

function getCurrGe() {
    return GS.ge[GS.hand_counter][GS.ply_counter]
}

function discardOverflowTest() {
    for (let pidx=0; pidx<4; pidx++) {
        // for (let i=0; i<27; i++) {
        for (let i=0; i<22; i++) {
            GS.ui.addDiscardTiles(pidx, ['1m'], false)
            if (i==15) {
                GS.ui.rotateLastTile(pidx, 'discard')
            }
        }
    }
    for (let pidx=0; pidx<4; pidx++) {
        GS.ui.addHandTiles(pidx, 'hand', [], true)
        GS.ui.addHandTiles(pidx, 'hand', ['6m'], false)
        GS.ui.addBlankSpace(pidx, true)
        GS.ui.addHandTiles(pidx, 'hand', ['7m'], false)

        for (let i=1; i<=4; i++) {
            console.log(i, tenhou2str(`${i}m`))
            GS.ui.addHandTiles(pidx, 'call', [`${i}m`], false)
            GS.ui.addHandTiles(pidx, 'call', [`${i}m`], false)
            GS.ui.addHandTiles(pidx, 'call', [`${i}m`], false)
            GS.ui.rotateLastTile(pidx, 'hand')
            GS.ui.addHandTiles(pidx, 'call', [`${i}m`], false)
            GS.ui.rotateLastTile(pidx, 'hand')
            GS.ui.floatLastTile(pidx)
        }
    }
}

function debugState() {
    console.log('GS.fullData:', GS.fullData)
    console.log('GS.ge', GS.ge)
    console.log(`GS.ge[${GS.hand_counter}]`, GS.ge[GS.hand_counter])
    console.log('hand', GS.hand_counter)
    console.log('ply', GS.ply_counter)
    console.log('event', getCurrGe())
}

function parseUrl() {
    const urlParams = new URLSearchParams(window.location.search)
    let dataParam = urlParams.get('data')
    let hand_counter = Number(urlParams.get('hand'))
    let ply_counter = Number(urlParams.get('ply'))
    if (urlParams.get('showMortal')) {
        GS.showMortal = Number(urlParams.get('showMortal'))
    }
    if (urlParams.get('alphaTestMode')) {
        GS.alphaTestMode = true
    }
    if (!dataParam) return
    var xhr = new XMLHttpRequest();
    xhr.open('GET', `${dataParam}`, true);
    xhr.responseType = 'json';
    xhr.onload = function() {
        var status = xhr.status;
        if (status == 200) {
            setMortalJsonStr(xhr.response)
            GS.hand_counter = 0
            GS.ply_counter = 0
            if (hand_counter !== null && hand_counter < GS.ge.length) {
                GS.hand_counter = hand_counter
            }
            if (ply_counter !== null && ply_counter < GS.ge[GS.hand_counter].length) {
                GS.ply_counter = ply_counter
            }
            updateState()
            connectUI()
        } else {
            alert(`载入失败：${dataParam} ${xhr.statusText}`)
        }
    };
    xhr.send();
}

/* ======================= 局 / 巡 跳转导航 ======================= */
// NAV[h] = { name:'东1', per:[每个 ply 的巡目], jun:[{n, ply}] }
let NAV = null
let NAV_BAD = {}          // hand -> Map(巡目 -> {level, ply, tag})

/* 恶手分级：判据与阈值存在配置里（设置面板可改），分级函数在 badlevel.js，
   页面与 node 单测共用同一份实现。 */
const BL = window.BadLevel
let BAD_CFG = BL ? BL.normalize(null)
    : { thresh: 0.10, gap: { severe: 0.50 }, loss: { severe: 0.70, medium: 0.30 } }

function levelCls(lv) { return 'lv-' + lv }
function levelOrder(lv) { return BL ? BL.order(lv) : 0 }
function levelZh(lv) { return (BL && BL.zh(lv)) || lv }
function badLevelOf(mv) { return BL ? BL.levelOf(mv, BAD_CFG) : 'severe' }
function badValueText(mv) { return BL ? BL.fmtGap(mv) : '' }
function badLossText(mv) { return BL ? BL.fmtQ(mv) : '' }
/** 徽章上的损失程度：只看 Q 损失，与巡目染色（权重差）互不影响。 */
function hitLossLevel(mv) { return BL ? BL.lossLevel(mv, BAD_CFG) : 'minor' }

function applyBadCfg(cfg) {
    if (BL && cfg) BAD_CFG = BL.normalize(cfg)
    try {
        buildBadMarks()
        paintNav()
        if (GS.ge && COACH) renderCoach()
    } catch (e) { console.warn('applyBadCfg', e) }
}

function buildNav() {
    NAV = null
    if (!GS.ge || !GS.ge.length) return
    const hero = GS.heroPidx
    const split = (GS.fullData && GS.fullData.split_logs) || []
    const out = []
    for (let h = 0; h < GS.ge.length; h++) {
        let name = '第' + (h + 1) + '局'
        try {
            const raw = split[h].log[0][0]
            const w = ['东', '南', '西', '北'][Math.floor(raw[0] / 4)]
            name = (w || '') + ((raw[0] % 4) + 1)
            if (raw[1] > 0) name += '-' + raw[1]        // 本场
        } catch (e) { }
        const evs = GS.ge[h]
        const per = new Array(evs.length)
        const jun = []
        const idxOf = new Map()
        let j = 0
        for (let ply = 0; ply < evs.length; ply++) {
            const e = evs[ply]
            if (e.type === 'tsumo' && e.actor === hero) j++   // 自家第几次摸牌 = 第几巡
            const me = e.mortalEval
            let jn = j
            if (me && me.junme) { jn = me.junme; j = me.junme }
            if (!jn) { per[ply] = 0; continue }
            per[ply] = jn
            const cur = idxOf.get(jn)
            if (!cur) {
                const rec = { n: jn, ply: ply, key: !!me }
                idxOf.set(jn, rec)
                jun.push(rec)
            } else if (me && !cur.key) {                      // 同一巡里优先停在我方决策点
                cur.ply = ply
                cur.key = true
            }
        }
        out.push({ name, per, jun })
    }
    NAV = out
    buildBadMarks()
}

function buildBadMarks() {
    NAV_BAD = {}
    if (!COACH || !COACH.moves) return
    for (const k of Object.keys(COACH.moves)) {
        const mv = COACH.moves[k]
        try {
            const lv = badLevelOf(mv)
            const parts = k.split(':')
            const h = Number(parts[0]), p = Number(parts[1])
            const rec = NAV && NAV[h]
            if (!rec) continue
            const jn = rec.per[p]
            if (!jn) continue
            const m = NAV_BAD[h] || (NAV_BAD[h] = new Map())
            const old = m.get(jn)
            // 同一巡里可能有多手：留更重的那一档（原来拿 sev === '决定性' 比较，
            // 但 sev 存的是「中等/明显」，这个条件永远不成立）
            if (!old || levelOrder(lv) > levelOrder(old.level)) {
                m.set(jn, { level: lv, tag: mv.tag || '', ply: p })
            }
        } catch (e) {
            // 一条脏数据不该让整局的标记全丢（历史文件可能来自旧版 pipeline）
            console.warn('bad move 解析失败', k, e)
        }
    }
}

function gotoJunme(h, jn) {
    if (!NAV || !NAV[h]) return
    const rec = NAV[h].jun.find(x => x.n === jn)
    if (!rec) return
    const bad = NAV_BAD[h] && NAV_BAD[h].get(jn)
    GS.hand_counter = h
    GS.ply_counter = bad ? bad.ply : rec.ply        // 该巡有恶手就直接停到恶手那一手
    updateState()
}

function gotoHand(h) {
    if (!NAV || !NAV[h] || !NAV[h].jun.length) return
    const m = NAV_BAD[h]
    if (m && m.size) {                        // 这局有恶手 → 直接停到第一处
        const first = NAV[h].jun.find(x => m.has(x.n))
        if (first) return gotoJunme(h, first.n)
    }
    gotoJunme(h, NAV[h].jun[0].n)
}

function paintLegend() {
    const el = document.getElementById('nv-legend')
    if (!el) return
    const on = ['severe', 'medium']
    el.innerHTML = on.map(l => `<span class="nv-lg ${levelCls(l)}"><i></i>${levelZh(l)}</span>`).join('')
}

/** 当前分级下所有恶手，按（局, 手）排序。 */
function badList() {
    const out = []
    Object.keys(NAV_BAD).forEach(h => {
        NAV_BAD[h].forEach(v => out.push([Number(h), v.ply]))
    })
    return out.sort((a, b) => a[0] - b[0] || a[1] - b[1])
}

/** 上一 / 下一恶手：直接在分级过滤后的清单里跳。
 *
 * 早先是一手一手往前挪、靠 stopCondition 判断，会停在「一局的最后一手」
 * （那里没有我方决策，面板只能显示「非我方决策」）。改成按清单跳就没这问题。
 */
function jumpBad(dir) {
    const list = badList()
    if (!list.length) return false
    const ch = GS.hand_counter, cp = GS.ply_counter
    let next = null
    if (dir > 0) {
        next = list.find(x => x[0] > ch || (x[0] === ch && x[1] > cp)) || list[0]
    } else {
        for (let i = list.length - 1; i >= 0; i--) {
            if (list[i][0] < ch || (list[i][0] === ch && list[i][1] < cp)) { next = list[i]; break }
        }
        if (!next) next = list[list.length - 1]
    }
    GS.hand_counter = next[0]
    GS.ply_counter = next[1]
    updateState()
    return true
}

function paintNav() {
    const kSel = document.getElementById('nv-kyoku')
    const jSel = document.getElementById('nv-junme')
    if (!kSel || !jSel) return
    paintLegend()
    if (!NAV) buildNav()
    if (!NAV || !NAV.length) { kSel.innerHTML = ''; jSel.innerHTML = ''; return }
    // 兜底：COACH 里明明有恶手、NAV_BAD 却是空的 —— 只可能是「NAV 先建好、coach 后到」
    // 这条时序把标记漏了。这里补建一次，别让用户非得「重新进一次」。
    if (!Object.keys(NAV_BAD).length && COACH && COACH.moves) {
        buildBadMarks()
    }
    const h = GS.hand_counter
    // 局数：只写「· 恶手 N 处」，不上色 —— 一局里 80% 的巡都可能是恶手，
    // 给整个局染色等于没有信息量；颜色只留给巡目。
    kSel.innerHTML = NAV.map((r, i) => {
        const bad = NAV_BAD[i] ? NAV_BAD[i].size : 0
        return `<option value="${i}">${esc(r.name)}局`
            + `${bad ? ' · 恶手 ' + bad + ' 处' : ''}</option>`
    }).join('')
    kSel.value = String(h)
    kSel.className = ''
    kSel.onchange = () => gotoHand(+kSel.value)
    // 巡目：另一个下拉，只列当前局的巡；恶手巡按档位染色并写明档位
    const cur = NAV[h]
    if (!cur || !cur.jun.length) { jSel.innerHTML = ''; jSel.className = ''; return }
    const curJn = cur.per[GS.ply_counter] || cur.jun[0].n
    const bad = NAV_BAD[h] || new Map()
    jSel.innerHTML = cur.jun.map(x => {
        const hit = bad.get(x.n)
        const suffix = hit ? ` · ${levelZh(hit.level)}` : ''
        return `<option value="${x.n}"${hit ? ` class="${levelCls(hit.level)}"` : ''}>`
            + `第 ${x.n} 巡${suffix}</option>`
    }).join('')
    jSel.value = String(curJn)
    const jw = bad.has(curJn) ? bad.get(curJn).level : ''
    jSel.className = jw ? 'hasbad ' + levelCls(jw) : ''
    jSel.onchange = () => gotoJunme(h, +jSel.value)
}

/* ======================= 牌谱库 · 评分 · 逐手解读 ======================= */
let COACH = null
let COACH_IDX = []
let RATED_FOR = null
let HISTORY = []

function isHomeView() {
    const p = new URLSearchParams(location.search)
    if (p.get('data')) return false
    return true
}

/* pywebview 的 api 是页面加载后才注入的：早一点读就会落到「浏览器模式」分支，
   于是历史筛选下拉变成空的、env 自检也拿不到。这里统一等它就位。 */
function hasBridge() { return !!(window.pywebview && window.pywebview.api) }
function waitBridge(timeout = 2500) {
    if (hasBridge()) return Promise.resolve(true)
    return new Promise(res => {
        let done = false
        const finish = ok => {
            if (done) return
            done = true
            clearInterval(timer)
            clearTimeout(limit)
            res(ok)
        }
        const timer = setInterval(() => { if (hasBridge()) finish(true) }, 100)
        const limit = setTimeout(() => finish(hasBridge()), timeout)
        window.addEventListener('pywebviewready', () => finish(true), { once: true })
    })
}

function homeUrl() { return location.pathname + '?view=home' }
function gameUrl(tag) { return location.pathname + '?data=' + encodeURIComponent('report/' + tag + '.json') }

function setHomeVisibility(home) {
    document.body.classList.toggle('home-mode', !!home)
    // 主页与「牌桌 + 侧栏 + 解读」是两套界面，一次只显示一套
    document.querySelectorAll('.grid-main, .sidebar, .coach-panel').forEach(el => {
        el.classList.toggle('home-hidden', !!home)
    })
    const hv = document.getElementById('home-view')
    if (hv) hv.style.display = home ? '' : 'none'
}

async function loadHistory() {
    const ready = await waitBridge(8000)
    if (!ready) window.addEventListener('pywebviewready', () => { loadHistory() }, { once: true })
    if (ready && window.pywebview && window.pywebview.api && window.pywebview.api.list_history) {
        try { HISTORY = await window.pywebview.api.list_history() } catch (e) { HISTORY = [] }
    } else {
        // 桥还没注入时的兜底：index.json 是升序，这里要翻成「最新在上」，
        // 否则页面刚打开的一瞬间历史会从最早的局开始排。
        HISTORY = COACH_IDX.map(x => ({...x, date: x.tag || '', year: 0, month: 0, day: 0}))
            .sort((a, b) => String(b.tag).localeCompare(String(a.tag)))
    }
    syncDateSelects()
    renderHistory()
}

// 只把「真的有牌谱」的年 / 月 / 日放进下拉，并且三级联动：
// 选了 2026 之后，月份里就只有 2026 出现过的月份；选到具体某一天同理。
function histOf(year, month) {
    return HISTORY.filter(x => (!year || x.year === year) && (!month || x.month === month))
}

function fillSel(id, items, label) {
    const el = document.getElementById(id); if (!el) return
    const old = el.value
    el.innerHTML = '<option value="">' + label + '</option>'
        + items.map(it => '<option value="' + it[0] + '">' + esc(it[1]) + '</option>').join('')
    el.value = items.some(it => String(it[0]) === String(old)) ? old : ''
}

function syncDateSelects() {
    const yEl = document.getElementById('history-year')
    const mEl = document.getElementById('history-month')
    if (!yEl || !mEl) return

    // 年份：从数据里取，倒序（最近的在最上面）
    const years = [...new Set(HISTORY.map(x => x.year).filter(Boolean))].sort((a, b) => b - a)
    fillSel('history-year', years.map(v => [v, v + ' 年']), '全部年份')
    const y = Number(yEl.value || 0)

    // 月份：只列这一年有牌谱的月份
    const months = [...new Set(histOf(y, 0).map(x => x.month).filter(Boolean))].sort((a, b) => a - b)
    fillSel('history-month', months.map(v => [v, v + ' 月']), '全部月份')
    const m = Number(mEl.value || 0)

    // 日期：只列这一年这一月有牌谱的日子
    const days = [...new Set(histOf(y, m).map(x => x.day).filter(Boolean))].sort((a, b) => a - b)
    fillSel('history-day', days.map(v => [v, v + ' 日']), '全部日期')
}

function renderHistory() {
    const box = document.getElementById('history-list'); if (!box) return
    const y = Number(document.getElementById('history-year')?.value || 0)
    const m = Number(document.getElementById('history-month')?.value || 0)
    const d = Number(document.getElementById('history-day')?.value || 0)
    const rows = HISTORY.filter(x => (!y || x.year === y) && (!m || x.month === m) && (!d || x.day === d))

    // 总数与平均评分：只在主页顶部露一行，省得每个下拉都重复「时间 / 日期 / 对局」

    const cnt = document.getElementById('hv-count')
    if (cnt) cnt.textContent = HISTORY.length ? `共 ${HISTORY.length} 局` : ''
    const sum = document.getElementById('hv-sum')
    if (sum) {
        if (!HISTORY.length) sum.textContent = '还没有分析过的牌谱 —— 先用左边那个框粘一条链接试试。'
        else {
            const rs = HISTORY.map(x => x.rating).filter(v => typeof v === 'number' && v > 0)
            const avg = rs.length ? (rs.reduce((a, b) => a + b, 0) / rs.length).toFixed(1) : '—'
            const bad = HISTORY.reduce((a, x) => a + (x.bad || 0), 0)
            sum.textContent = `已分析 ${HISTORY.length} 局 · 平均 rating ${avg} · 恶手合计 ${bad} 手`
        }
    }

    if (!rows.length) {
        box.innerHTML = '<div class="history-empty">' + (HISTORY.length ? '这个时间段没有牌谱' : '还没有历史牌谱 —— 分析一局后会自动出现在这里；也可以点右上角 ⚙ 设置换个牌谱库目录') + '</div>'
        return
    }
    box.innerHTML = rows.map(x => {
        const on = (curTag() || sessionStorage.getItem('mc_last_tag') || '') === x.tag ? ' is-current' : ''
        return '<div class="history-row' + on + '" data-tag="' + esc(x.tag) + '">'
            + '<div class="hr-main"><b>' + esc(x.date || x.tag) + ' · ' + esc(x.tag) + '</b>'
            + '<small>rating ' + (x.rating == null ? '—' : x.rating)
            + ' · 恶手 ' + (x.bad || 0) + ' 手 · ' + (x.kyoku || 0) + ' 局</small></div>'
            + '<span><button data-open="' + esc(x.tag) + '">打开</button>'
            + '<button data-del="' + esc(x.tag) + '">删除</button></span></div>'
    }).join('')
    box.querySelectorAll('.history-row').forEach(row => {
        row.onclick = e => {
            if (e.target.closest('[data-del]')) return
            location.href = gameUrl(row.dataset.tag)
        }
    })
    box.querySelectorAll('[data-open]').forEach(b => b.onclick = () => { location.href = gameUrl(b.dataset.open) })
    box.querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
        if (!confirm('确定删除 ' + b.dataset.del + '？')) return
        if (!(window.pywebview && window.pywebview.api && window.pywebview.api.delete_game)) return
        const r = await window.pywebview.api.delete_game(b.dataset.del)
        if (!r || !r.ok) { alert((r && r.msg) || '删除失败'); return }
        await initLibrary(); await loadHistory()
    })
}

function t2zh(t) {
    if (t === null || t === undefined || t === '') return '?'
    if (typeof t === 'number') {                       // 136 张编码：id>>2 得牌种
        const tile = Math.floor(t / 4)
        const suit = Math.floor(tile / 9)
        const num = tile % 9 + 1
        if (suit === 3) return ['东', '南', '西', '北', '白', '发', '中'][num - 1] || String(t)
        const red = (t === 16 || t === 52 || t === 88)
        return num + ['万', '筒', '索'][suit] + (red ? '(赤)' : '')
    }
    const s = String(t)
    const m = s.match(/^([0-9])([mps])(r?)$/)
    if (m) {
        const suit = { m: '万', p: '筒', s: '索' }[m[2]]
        const n = m[1] === '0' ? '5' : m[1]
        return n + suit + (m[1] === '0' || m[3] ? '(赤)' : '')
    }
    return ({ E: '东', S: '南', W: '西', N: '北', P: '白', F: '发', C: '中' })[t] || t
}
function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c])
}
function curTag() {
    const d = new URLSearchParams(location.search).get('data') || ''
    const m = d.match(/([^\/\\]+)\.json$/)
    return m ? m[1] : ''
}

function renderRating() {
    const n = document.getElementById('rate-num')
    const s = document.getElementById('rate-sub')
    if (!n || !s || !GS.fullData || !GS.fullData.review) return
    if (RATED_FOR === GS.fullData) return
    RATED_FOR = GS.fullData
    const rv = GS.fullData.review
    const v = (rv.rating || 0) * 100
    n.textContent = v.toFixed(1)
    n.className = 'rate-num' + (v < 80 ? ' bad' : (v < 87 ? ' low' : ''))
    const m = rv.total_matches, r = rv.total_reviewed
    const pct = r ? Math.round(m / r * 100) : 0
    s.innerHTML = `rating　${m}/${r} 一致（${pct}%）<br>Mortal ${esc(rv.model_tag || '')}`
}

function lineCls(t) {
    if (t.startsWith('【')) return 'cp-h'
    if (t.startsWith('场况') || t.startsWith('点数') || t.startsWith('顺位')) return 'cp-now'
    if (t.startsWith('手牌')) return 'cp-cond'
    if (t.startsWith('做牌')) return 'cp-yaku'
    if (t.startsWith('攻守')) return 'cp-policy'
    if (t.startsWith('威胁')) return 'cp-threat'
    if (t.startsWith('本钱')) return 'cp-cap'
    if (t.startsWith('退路')) return 'cp-exit'
    if (t.startsWith('这一张的风险')) return 'cp-risk'
    if (t.startsWith('为什么')) return 'cp-why'
    if (t.startsWith('→') || t.startsWith('账')) return 'cp-sub'
    // 主判据（①②③…）：带「决定性」的那一条单独上色，一眼能看出这手的胜负手
    if (/^[①②③④⑤]/.test(t)) return t.indexOf('（决定性）') >= 0 ? 'cp-key cp-dec' : 'cp-key'
    if (t.startsWith('原理')) return 'cp-tax'
    if (t.startsWith('结论')) return 'cp-concl'
    if (t.startsWith('Mortal 评分')) return 'cp-score'
    if (t.startsWith('——')) return 'cp-ref'
    return 'cp-cond'
}
// 正文里的牌名统一写成 {{2m}}，在这里换成牌面图；其余文字照常转义。
// 只认 <数字+花色> 或单个字牌码，避免把「东1局」这类普通文字吃掉。
function inlineTiles(s) {
    return String(s == null ? '' : s).split(/(\{\{[0-9][mps]r?\}\}|\{\{[ESWNPFC]\}\})/)
        .map(part => {
            const m = part.match(/^\{\{([0-9][mps]r?|[ESWNPFC])\}\}$/)
            return m ? `<span class="cp-t">${tileChip(m[1])}</span>` : esc(part)
        }).join('')
}
function renderText(text) {
    if (!text) return ''
    return text.split('\n').map(raw => {
        const t = raw.trim()
        if (!t) return ''
        const sub = /^\s{2,}/.test(raw)              // 两格以上缩进 = 上一行的论据
        let cls = lineCls(t)
        if (sub && cls.indexOf('cp-sub') < 0) cls += ' cp-sub'
        return `<span class="cp-l ${cls}">${inlineTiles(t)}</span>`
    }).join('')
}
// 把 Mortal 的动作对象（{act,pai} 或 {type,pai}）写成人话
function actLabel(a) {
    if (!a) return '—'
    const type = a.act || a.type
    if (type === 'dahai') return '打 ' + t2zh(a.pai)
    if (type === 'reach') return '立直'
    if (type === 'none') return '过'
    return (type || '') + (a.pai ? ' ' + t2zh(a.pai) : '')
}

// 中间栏常驻的候选表：不再写成一整句文字，直接排版成「选择 / 权重 / Q」三列。
// 侧栏只有 ~280px，所以牌名省略「打 」前缀、差值收进 title，保持一行一条不折行。
function candName(x) {
    const s = actLabel(x)
    return s.indexOf('打 ') === 0 ? s.slice(2) : s
}

function weightTable(rows, expNm, actNm) {
    if (!rows || !rows.length) return ''
    const base = rows[0].q
    const body = rows.map((x, i) => {
        const isExp = !!expNm && x.nm === expNm
        const isAct = !!actNm && x.nm === actNm
        const mark = isExp ? '<em class="mark-exp" title="Mortal 的最优选择">★</em>'
            : (isAct ? '<em class="mark-act" title="你实战打的那张">·你</em>' : '')
        // 条长就用权重本身（0~100%），不做相对归一 —— 49% 和 42% 本来就该差不多长
        const w = Math.max(1.5, Math.min(100, (x.p || 0) * 100))
        const d = (x.q - base)
        const tip = '权重 ' + ((x.p || 0) * 100).toFixed(1) + '%，Q ' + x.q.toFixed(3)
            + (i ? '（比最优低 ' + Math.abs(d).toFixed(3) + '）' : '（最优）')
        return '<div class="cp-cand' + (isExp ? ' is-exp' : '') + (isAct ? ' is-act' : '') + '"'
            + ' title="' + esc(tip) + '">'
            + '<b>' + esc(x.nm) + mark + '</b>'
            + '<span class="bar"><i style="width:' + w.toFixed(1) + '%"></i></span>'
            + '<span class="pct">' + ((x.p || 0) < 0.001 ? '<0.1%' : ((x.p || 0) * 100).toFixed(1) + '%') + '</span>'
            + '<span class="q">' + x.q.toFixed(3) + '</span></div>'
    }).join('')
    return '<div class="cp-cands">' + body + '</div>'
}

// 把当前这一手的候选写进中间栏。hit 是恶手记录（带 top）；没有恶手就说明一句。
function paintWeight(hit) {
    const body = document.getElementById('w-body')
    if (!body) return
    const top = hit && Array.isArray(hit.top) ? hit.top : []
    if (!top.length) {
        body.innerHTML = '<span class="w-empty">这一巡和 Mortal 一致，没有需要比对的候选。</span>'
        return
    }
    const expNm = hit.expect ? candName({ act: 'dahai', pai: hit.expect }) : ''
    const actNm = hit.actual ? candName({ act: 'dahai', pai: hit.actual }) : ''
    const rows = top.slice(0, 6).map(x => ({ nm: candName(x), p: x.p, q: x.q }))
    body.innerHTML = weightTable(rows, expNm, actNm)
        + '<div class="cp-cand-note">按 Q 值排序；百分比 = softmax(Q/τ)，只是它当时的倾向，不是胜率。Q 差越大，这一手亏得越多。</div>'
}

function candRows(me) {    if (!me || !Array.isArray(me.details) || !me.details.length) return ''
    // 136 编码下同一牌种可能有多个 id → 先按牌名合并，取概率最大的那条
    const byName = new Map()
    for (const d of me.details) {
        const act = d.action || {}
        let nm
        if (act.type === 'dahai') nm = '打' + t2zh(act.pai)
        else if (act.type === 'reach') nm = '立直'
        else if (act.type === 'none') nm = '过'
        else nm = (act.type || '') + (act.pai != null ? t2zh(act.pai) : '')
        const p = d.normProb != null ? d.normProb : (d.prob || 0)
        const old = byName.get(nm)
        if (!old || p > old.p) byName.set(nm, { nm, p, act })
    }
    const top = [...byName.values()].sort((a, b) => b.p - a.p).slice(0, 5)
    if (!top.length) return ''
    const max = top[0].p || 1
    const expName = me.expected ? (me.expected.type === 'dahai' ? '打' + t2zh(me.expected.pai)
        : (me.expected.type === 'reach' ? '立直' : '过')) : null
    const actName = me.actual ? (me.actual.type === 'dahai' ? '打' + t2zh(me.actual.pai)
        : (me.actual.type === 'reach' ? '立直' : '过')) : null
    return `<div class="cp-cands">${top.map(x => {
        const w = Math.max(2, Math.round(x.p / max * 100))
        const mark = (x.nm === expName) ? ' ★' : (x.nm === actName ? ' ·你' : '')
        return `<div class="cp-cand"><b>${esc(x.nm)}${mark}</b>`
            + `<span class="bar"><i style="width:${w}%"></i></span>`
            + `<span>${(x.p * 100).toFixed(0)}%</span></div>`
    }).join('')}</div>`
}

let COACH_STEP = 0
let COACH_STEP_KEY = ''

const SIDE_CLS = { '攻': 'a', '守': 'd', '判': 'j', '局': 's', '结': 'c', '评': 'v' }

function paintSteps(steps, cur) {
    const rail = document.getElementById('cp-rail')
    const nav = document.getElementById('cp-nav')
    const head = document.getElementById('cp-pagehead')
    const cnt = document.getElementById('cp-count')
    if (!rail || !nav) return
    rail.style.display = 'flex'      // clearSteps 会把它隐藏，这里必须恢复
    rail.innerHTML = steps.map((s, i) => {
        const c = 'cp-dot' + (i === cur ? ' on' : '') + (i < cur ? ' done' : '')
            + ' sd-' + (SIDE_CLS[s.side] || 'x')
        const bg = s.badge ? ' · ' + s.badge : ''
        return `<button type="button" class="${c}" data-step="${i}" title="${esc(s.t + bg)}">${i + 1}</button>`
    }).join('')
    rail.querySelectorAll('.cp-dot').forEach(b => {
        b.onclick = () => { COACH_STEP = +b.dataset.step; renderCoach() }
    })
    head.style.display = 'flex'
    const sideEl = document.getElementById('cp-side')
    sideEl.textContent = steps[cur].side || ''
    sideEl.className = 'cp-side sd-' + (SIDE_CLS[steps[cur].side] || 'x')
    document.getElementById('cp-pagetitle').textContent = steps[cur].t || ''
    const badge = document.getElementById('cp-badge')
    badge.textContent = steps[cur].badge || ''
    badge.style.display = steps[cur].badge ? 'inline-block' : 'none'
    if (cnt) cnt.textContent = (cur + 1) + ' / ' + steps.length
    const prev = document.getElementById('cp-prev')
    const next = document.getElementById('cp-next')
    prev.disabled = cur === 0
    next.disabled = cur >= steps.length - 1
    prev.onclick = () => { if (COACH_STEP > 0) { COACH_STEP--; renderCoach() } }
    next.onclick = () => { if (COACH_STEP < steps.length - 1) { COACH_STEP++; renderCoach() } }
    nav.style.display = 'flex'
}

function clearSteps() {
    const rail = document.getElementById('cp-rail')
    const nav = document.getElementById('cp-nav')
    if (rail) { rail.innerHTML = ''; rail.style.display = 'none' }
    if (nav) nav.style.display = 'none'          // 只隐藏：里面还有按钮和页码，清空会丢节点
    const head = document.getElementById('cp-pagehead')
    if (head) head.style.display = 'none'
}

// 键盘：[ 上一步 / ] 下一步（方向键已被「走巡」占用）
document.addEventListener('keydown', (e) => {
    if (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return
    if (e.key !== '[' && e.key !== ']') return
    const rail = document.getElementById('cp-rail')
    const n = rail ? rail.children.length : 0
    if (!n) return
    if (e.key === '[' && COACH_STEP > 0) { COACH_STEP--; renderCoach() }
    if (e.key === ']' && COACH_STEP < n - 1) { COACH_STEP++; renderCoach() }
    e.preventDefault()
})

function tileFile(t) {
    if (!t) return '1z'
    const z = { E: '1z', S: '2z', W: '3z', N: '4z', P: '5z', F: '6z', C: '7z' }
    if (z[t]) return z[t]
    return String(t).replace(/r$/, '')        // '5mr' → '5m'（赤 5 用同花色牌面）
}

function tileChip(t, extra) {
    // 用真正的牌面图（media/Regular_shortnames/*.svg），不再画「白底 + 文字」的假牌
    const f = tileFile(t)
    return `<img class="hb-t${extra ? ' ' + extra : ''}" src="media/Regular_shortnames/${f}.svg"`
        + ` alt="${esc(t2zh(t))}" title="${esc(t2zh(t))}" draggable="false">`
}

function ukOrder(t) {
    // 有效牌按「万→筒→索→字、数字升序」排，和手牌顺序一致，扫一眼就能对上
    const z = { E: 1, S: 2, W: 3, N: 4, P: 5, F: 6, C: 7 }
    if (z[t]) return 400 + z[t]
    const n = t[0] === '0' ? 5 : (parseInt(t[0], 10) || 0)
    const s = t[1] === 'p' ? 100 : (t[1] === 's' ? 200 : 0)
    return s + n
}

function handBlock(label, cls, h) {
    if (!h || !h.hand || !h.hand.length) return ''
    const groups = (h.groups || []).map(([lab, ts]) =>
        `<span class="hb-g${lab === '浮牌' ? ' f' : ''}">${ts.map(tileChip).join('')}</span>`).join('')
    const labs = (h.groups || []).map(([lab, ts]) => lab)
    // 有效牌全部列出（超宽自动换行）：不再用「+N」省略，牌面本身就说明是哪些牌
    const uk = Object.keys(h.uk || {}).sort((a, b) => ukOrder(a) - ukOrder(b)).map((t) =>
        `<span class="hb-u">${tileChip(t)}<em>${h.uk[t]}</em></span>`
    ).join('')
    const sh = (h.shanten === 0) ? '听牌' : (h.shanten == null ? '' : h.shanten + ' 向听')
    return `<div class="hb ${cls}">
        <div class="hb-h"><i>${label}</i>切 ${tileChip(h.cut)}<span class="hb-sh">${sh}</span></div>
        <div class="hb-row">${groups}</div>
        <div class="hb-lab">${labs.join(' · ')}</div>
        <div class="hb-uk"><span class="hb-uklb">有效牌</span>`
        + `<span class="hb-sum">${h.kinds || 0} 种 ${h.tiles || 0} 枚</span>${uk || '—'}</div>
    </div>`
}

// 改良牌单独成块（不再塞在有效牌下面）：两种切法左右对照，和正文「② 将来性（改良）」一一对应
function impCol(label, cls, h) {
    if (!h) return ''
    const keys = Object.keys(h.imp || {}).sort((a, b) => ukOrder(a) - ukOrder(b))
    const imp = keys.map((t) =>
        `<span class="hb-u">${tileChip(t)}<em>${h.imp[t]}</em></span>`).join('')
    const n = keys.reduce((a, t) => a + (h.imp[t] || 0), 0)
    return `<div class="imp-col ${cls}">
        <div class="imp-h"><i>${label}</i>切 ${tileChip(h.cut)}`
        + `<span class="imp-n">${n ? '改良 ' + n + ' 枚' : '无改良'}</span></div>
        <div class="imp-t">${imp || '<span class="imp-none">没有能降向听 / 放宽进张的牌</span>'}</div>
    </div>`
}
function impBlock(exp, act) {
    const has = (h) => !!(h && h.imp && Object.keys(h.imp).length)
    if (!has(exp) && !has(act)) return ''
    return `<div class="imp-card">
        <div class="imp-ttl">改良牌<em>摸到后能降向听，或向听不变但把进张放宽（已扣掉现有进张）</em></div>
        <div class="imp-grid">${impCol('Mortal', 'hb-exp', exp)}${impCol('实战', 'hb-act', act)}</div>
    </div>`
}

function nowBlock(n) {
    if (!n || !n.hand || !n.hand.length) return ''
    let found = false
    const chip = (t) => {
        const isNew = !found && n.drawn && t === n.drawn
        if (isNew) found = true
        return tileChip(t, isNew ? 'dr' : '')
    }
    const groups = (n.groups || []).map(([lab, ts]) =>
        `<span class="hb-g${lab === '浮牌' ? ' f' : ''}">${ts.map(chip).join('')}</span>`).join('')
    const dr = n.drawn ? `　摸到 ${tileChip(n.drawn)}` : ''
    return `<div class="hb hb-now">
        <div class="hb-h"><i>当前手牌</i>${dr}</div>
        <div class="hb-row">${groups}</div>
    </div>`
}

function renderCoach() {
    const body = document.getElementById('cp-body')
    const sevEl = document.getElementById('cp-sev')
    if (!body) return
    // 标题栏左上角：这一手在哪一局哪一巡
    const loc = document.getElementById('cp-loc')
    if (loc) {
        const r = NAV && NAV[GS.hand_counter]
        const jn = r ? (r.per[GS.ply_counter] || '') : ''
        loc.textContent = r ? (r.name + '局' + (jn ? ' · 第' + jn + '巡' : '')) : ''
    }
    const ge = (GS.ge && GS.ge[GS.hand_counter]) ? GS.ge[GS.hand_counter][GS.ply_counter] : null
    if (!ge) { body.innerHTML = '<span class="cp-empty">没有这一巡</span>'; clearSteps(); paintWeight(null); return }
    const key = GS.hand_counter + ':' + GS.ply_counter
    const hit = COACH && COACH.moves ? COACH.moves[key] : null

    // 中间栏的候选表跟着当前这一手走（不管解读翻到第几页都常驻）
    paintWeight(hit)

    if (hit) {
        // 徽章只讲「损失程度」——这一手真正亏了多少（Q 差）。
        // 权重差在权重表里看得到，巡目颜色也已经表达了它，这里不重复。
        const lossLv = hitLossLevel(hit)
        sevEl.innerHTML = '<b>损失 ' + levelZh(lossLv) + '</b>'
        sevEl.className = 'cp-sev ' + (lossLv === 'severe' ? 's1' : (lossLv === 'medium' ? 's2' : 's4'))
        const bits = [hit.tag, hit.gap != null ? badValueText(hit) : '', badLossText(hit)].filter(Boolean)
        sevEl.title = bits.join(' · ') + '（期望差，不是点数；越大越亏）'
        // 「候选评分」已经从解读分页里拿掉了：权重表常驻在中间栏，这里跳过那一页
        const raw = (hit.steps && hit.steps.length)
            ? hit.steps : [{ k: 'state', t: '解读', side: '局', b: hit.text }]
        const steps = raw.filter(s => s.k !== 'cand')
        if (!steps.length) steps.push({ k: 'state', t: '解读', side: '局', b: hit.text })
        if (COACH_STEP_KEY !== key) { COACH_STEP_KEY = key; COACH_STEP = 0 }
        if (COACH_STEP >= steps.length) COACH_STEP = 0
        const st = steps[COACH_STEP]
        let html = ''
        html += renderText(st.b || '')
        if (st.k === 'state' && hit.now) html += nowBlock(hit.now)
        if (st.k === '牌效' && hit.hands) {
            html += handBlock('Mortal 的切法', 'hb-exp', hit.hands.exp)
            html += handBlock('实战的切法', 'hb-act', hit.hands.act)
            html += impBlock(hit.hands.exp, hit.hands.act)
        }
        html += st.html || ''
        body.innerHTML = html
        body.scrollTop = 0
        paintSteps(steps, COACH_STEP)
        return
    }

    const me = ge.mortalEval
    if (!me) {
        sevEl.textContent = '非我方决策'
        sevEl.className = 'cp-sev'
        sevEl.title = ''
        clearSteps()
        body.innerHTML = '<span class="cp-empty">这一巡不是你的选择点（别家摸打或结算）。<br>按右侧 <b>Next Error</b> 跳到下一处需要解读的手。</span>'
        return
    }
    sevEl.textContent = '与 Mortal 一致'
    sevEl.className = 'cp-sev s3'
    sevEl.title = ''
    const act = me.actual && me.actual.type === 'dahai' ? '打 ' + t2zh(me.actual.pai)
        : (me.actual && me.actual.type === 'reach' ? '立直' : (me.actual && me.actual.type === 'none' ? '过' : '—'))
    const exp = me.expected && me.expected.type === 'dahai' ? '打 ' + t2zh(me.expected.pai)
        : (me.expected && me.expected.type === 'reach' ? '立直' : (me.expected && me.expected.type === 'none' ? '过' : '—'))
    const qOf = (pai) => {
        const d = (me.details || []).find(x => x.action && x.action.pai === pai)
        return d && typeof d.q_value === 'number' ? d.q_value : null
    }
    const qa = qOf(me.actual && me.actual.pai)
    const qe = qOf(me.expected && me.expected.pai)
    const loss = (qa != null && qe != null) ? (qa - qe) : null

    let s1 = `<div class="cp-meta"><span>第 ${me.junme} 巡</span><span>残 ${me.tiles_left} 张</span>`
        + `<span>${me.shanten != null ? me.shanten + ' 向听' : ''}</span></div>`
    s1 += `<span class="cp-l cp-now">你：<b>${esc(act)}</b>　Mortal：<b>${esc(exp)}</b>`
        + (me.is_equal ? '　<span class="cp-concl">一致</span>' : '　<span class="cp-key">不一致但差距未达 10pt</span>') + `</span>`
    if (loss != null) {
        s1 += `<span class="cp-l cp-score">期望损失 ${loss >= 0 ? '+' : ''}${loss.toFixed(3)}　（Q 值 ${qa.toFixed(3)} vs ${qe.toFixed(3)}）</span>`
    }
    let s2 = candRows(me)
    s2 += `<span class="cp-l cp-ref">这一手差距不足 10pt，没有单独出解读；切到有红标的一手可看完整分析。</span>`

    const steps = [
        { k: 'state', t: '局面', side: '局', b: '', html: s1 },
        { k: 'cand', t: '候选评分', side: '评', b: '', html: s2 },
    ]
    if (COACH_STEP_KEY !== key) { COACH_STEP_KEY = key; COACH_STEP = 0 }
    if (COACH_STEP >= steps.length) COACH_STEP = 0
    body.innerHTML = (steps[COACH_STEP].b || '') + (steps[COACH_STEP].html || '')
    body.scrollTop = 0
    paintSteps(steps, COACH_STEP)
}

/** 读这一局的解读文件，覆盖到 COACH。
 *
 * 首次进入时 WebView2 的网络栈有时还没就绪，fetch 会直接失败一次（同页面的 XHR
 * 却成功），表现就是「第一次进没有恶手标记、下一恶手也不跳，重进一次才有」。
 * 所以这里必须自己重试，不能把一次失败当成「这一局没有解读」。
 * 404 只可能是文件真没生成，重试也没用，直接停。
 */
async function loadCoach(tag) {
    window.__coachLog = window.__coachLog || []
    window.__coachLog.push(['enter', String(tag), location.search])
    if (!tag) return
    if (!isHomeView()) sessionStorage.setItem('mc_last_tag', tag)
    COACH = null
    let err = ''
    for (let attempt = 0; attempt < 3; attempt++) {
        try {
            const r = await fetch(`coach/${tag}.json`, { cache: 'no-store' })
            window.__coachLog.push(['fetched', r.status, r.ok, attempt])
            if (r.ok) {
                COACH = await r.json()
                window.__coachLog.push(['json', COACH ? Object.keys(COACH).length : -1])
                break
            }
            err = `HTTP ${r.status}`
            if (r.status === 404) break          // 没生成的文件，重试也不会变
        } catch (e) {
            err = String((e && e.message) || e)
            window.__coachLog.push(['err', err, attempt])
        }
        await new Promise(res => setTimeout(res, 300 * (attempt + 1)))
    }
    if (!COACH) {
        console.warn(`coach/${tag}.json 读取失败：${err}`)
        const st = document.getElementById('link-status')
        if (st) {
            st.className = 'link-status bad'
            st.textContent = `解读文件没读到（${err}）。若反复出现，重开本局或重新生成解读。`
        }
    }
    try { buildBadMarks(); paintNav(); if (GS.ge) renderCoach() } catch (e) { console.warn('nav marks', e) }
}

// ---------------- 设置：牌谱库 / 浏览器 / 运行时 ----------------
const api = () => (window.pywebview && window.pywebview.api) || null
const $v = (id) => { const el = document.getElementById(id); return el ? el.value : '' }
const setV = (id, v) => { const el = document.getElementById(id); if (el) el.value = v == null ? '' : v }

// ---------------- 首次使用说明（记在配置里，设置里可重开） ----------------
const WELCOME_KEY = 'mc_welcome_v1'
let UI_FLAGS = {}

function welcomeSeen() {
    if (UI_FLAGS.welcome_done) return true
    try { return localStorage.getItem(WELCOME_KEY) === '1' } catch (e) { return false }
}

/** 页面状态写回配置（localStorage 只作降级备份）。 */
function saveUiFlag(patch) {
    UI_FLAGS = Object.assign({}, UI_FLAGS, patch)
    try {
        if (patch.welcome_done) localStorage.setItem(WELCOME_KEY, '1')
        else localStorage.removeItem(WELCOME_KEY)
    } catch (e) { }
    if (api() && api().set_settings) {
        try { api().set_settings({ ui: patch }) } catch (e) { console.warn('saveUiFlag', e) }
    }
}

function openWelcome(fromSettings) {
    const dlg = document.getElementById('welcome-modal')
    if (!dlg || dlg.open) return
    const never = document.getElementById('wl-never')
    // 从设置里手动重开时，勾选状态直接反「已经不再提示」这个事实；
    // 首次自动弹出则保持 HTML 的默认勾选（＝看完就关掉，别每次都弹）
    if (never && fromSettings) never.checked = true
    dlg.showModal()
}

function initWelcome() {
    const dlg = document.getElementById('welcome-modal')
    if (!dlg) return
    const never = document.getElementById('wl-never')
    // 关掉时按勾选状态决定下次还弹不弹：勾着 = 不再自动提示
    const remember = () => {
        saveUiFlag({ welcome_done: !never || never.checked })
    }
    dlg.querySelectorAll('.welcome-close').forEach(b => { b.onclick = () => { remember(); dlg.close() } })
    dlg.addEventListener('close', remember)
    const start = document.getElementById('wl-start')
    if (start) start.onclick = () => { remember(); dlg.close() }
    const toSet = document.getElementById('wl-open-settings')
    if (toSet) toSet.onclick = () => { remember(); dlg.close(); openSettings() }
    const help = document.getElementById('st-help')
    if (help) help.onclick = () => {
        const s = document.getElementById('settings-modal')
        if (s && s.open) s.close()
        openWelcome(true)
    }
    if (!welcomeSeen() && isHomeView()) setTimeout(openWelcome, 700)   // 只在第一次进主页时自动弹
}

/** 启动时把配置里的「页面状态 + 恶手分级」读进来（配置在 mortal-coach.json 里）。 */
async function loadUiCfg() {
    // pywebview 的 api 是页面加载后才注入的：不等它就永远读到默认值
    if (!api()) await waitBridge(4000)
    if (!api() || !api().get_settings) return
    try {
        const s = await api().get_settings()
        if (s && s.ui) UI_FLAGS = s.ui
        if (s && s.bad) applyBadCfg(s.bad)
    } catch (e) { console.warn('loadUiCfg', e) }
}

// ---------------- 设置：门槛 + 两档刻度 ----------------
/** 表单 → 配置。权重差表单里填的是百分数（10 / 50），Q 表单填的是小数（0.70）。 */
function fillBadForm(bad) {
    if (!BL) return
    const cfg = BL.normalize(bad)
    setV('st-bad-thresh', Math.round(cfg.thresh * 100))
    setV('st-bad-g-severe', Math.round(cfg.gap.severe * 100))
    setV('st-bad-q-severe', Number(cfg.loss.severe.toFixed(2)))
    setV('st-bad-q-medium', Number(cfg.loss.medium.toFixed(2)))
}

/** 读表单 → 配置。门槛或严重线填得不像话时返回 null，保存会拦下来。 */
function readBadCfg() {
    if (!BL) return null
    const cur = BL.normalize(BAD_CFG)
    const pct = (id, d) => {
        const n = Number($v(id))
        return isFinite(n) && n >= 0 && n <= 100 ? n / 100 : d
    }
    const q = (id, d) => {
        const n = Number($v(id))
        return isFinite(n) && n >= 0 ? n : d
    }
    const cfg = BL.normalize({
        thresh: pct('st-bad-thresh', cur.thresh),
        gap: { severe: pct('st-bad-g-severe', cur.gap.severe) },
        loss: {
            severe: q('st-bad-q-severe', cur.loss.severe),
            medium: q('st-bad-q-medium', cur.loss.medium),
        },
    })
    return cfg.thresh > 0 ? cfg : null
}

/** 库里每手的 [权重差, Q 损失]，开设置面板时拉一次，用来实时预览分档结果。 */
let BAD_POINTS = null;

/** 按当前表单里的门槛与严重线，把整库的手分档，写到权重差那一栏下面。 */
function paintBadCounts() {
    const out = document.getElementById('st-bad-count')
    if (!out) return
    if (!BL || !BAD_POINTS || !BAD_POINTS.length) { out.textContent = ''; return }
    const cfg = readBadCfg()
    if (!cfg) { out.textContent = '门槛要大于 0，否则什么都收不进来'; return }
    const kept = BAD_POINTS.filter(p => p[0] >= cfg.thresh)
    const s = BL.summary(kept.map(p => ({ gap: p[0], qloss: -Math.abs(p[1]) })), cfg)
    out.textContent = `库里现有 ${BAD_POINTS.length} 手 · 按当前门槛 ${BL.fmtGapThr(cfg.thresh)} 收进 `
        + `${kept.length} 手：严重 ${s.severe} · 中等 ${s.medium}（两档都解析、都标记）`
}

async function openSettings() {
    const dlg = document.getElementById('settings-modal')
    if (!dlg) return
    const msg = document.getElementById('st-msg')
    if (msg) msg.textContent = ''
    if (!api() || !api().get_settings) {
        if (msg) msg.textContent = '设置只能在桌面版里改'
        dlg.showModal()
        return
    }
    let s = null
    try { s = await api().get_settings() } catch (e) { console.warn('get_settings', e) }
    if (api().get_bad_points) {
        try { BAD_POINTS = await api().get_bad_points() } catch (e) { console.warn('get_bad_points', e) }
    }
    if (s) {
        if (s.ui) UI_FLAGS = s.ui
        fillBadForm(s.bad || {})
        setV('st-lib', s.library)
        setV('st-chrome', s.chrome)
        setV('st-python', s.python)
        setV('st-node', s.node)
        const cb = document.getElementById('st-show-browser')
        if (cb) cb.checked = !!s.show_browser
        const cnt = document.getElementById('st-count')
        if (cnt && s.counts) {
            cnt.textContent = `${s.counts.games} 局 · ${s.counts.reports} 份报告 · `
                + `${s.counts.images} 张图 · ${s.counts.mb} MB`
        }
        const env = document.getElementById('st-env')
        if (env) {
            // 三段各是一个 inline-block：长路径整体换行，不会被从盘符中间劈开
            const esc = t => String(t).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]))
            env.innerHTML = [['Python', s.python_found], ['Node', s.node_found],
                             ['浏览器', s.chrome_found], ['界面内核', s.webview2_found]]
                .map(([k, v]) => `<span class="st-env-i">${k}：${esc(v || '未找到')}</span>`).join('')
        }
        const lib = document.getElementById('st-lib')
        if (lib) lib.placeholder = s.library_default || ''
    }
    paintBadCounts()
    dlg.showModal()
}

async function saveSettings() {
    const msg = document.getElementById('st-msg')
    if (!api() || !api().set_settings) return
    const bad = readBadCfg()
    if (bad === null) {
        if (msg) msg.textContent = '门槛要大于 0（等于 0 会把整局每一手都收进来）'
        return
    }
    const patch = {
        library: $v('st-lib').trim(),
        chrome: $v('st-chrome').trim(),
        python: $v('st-python').trim(),
        node: $v('st-node').trim(),
        show_browser: !!(document.getElementById('st-show-browser') || {}).checked,
        bad: bad,
    }
    if (msg) msg.textContent = '保存中…'
    let r = null
    try { r = await api().set_settings(patch) } catch (e) { r = { ok: false, msg: String(e) } }
    if (msg) msg.textContent = (r && r.msg) || (r && r.ok ? '已保存' : '保存失败')
    if (r && r.ok) {
        const s = r.settings || {}
        if (s.library) setV('st-lib', s.library)
        if (s.counts) {
            const cnt = document.getElementById('st-count')
            if (cnt) cnt.textContent = `${s.counts.games} 局 · ${s.counts.reports} 份报告 · `
                + `${s.counts.images} 张图 · ${s.counts.mb} MB`
        }
        if (s.bad) applyBadCfg(s.bad)
        setTimeout(() => { location.href = homeUrl() }, 500)
    }
}

async function initSettings() {
    const btn = document.getElementById('btn-settings')
    if (btn) btn.onclick = openSettings
    const dlg = document.getElementById('settings-modal')
    if (!dlg) return
    dlg.querySelectorAll('.settings-close').forEach(b => { b.onclick = () => dlg.close() })
    const pick = document.getElementById('st-pick')
    if (pick) pick.onclick = async () => {
        if (!api() || !api().pick_library) return
        const r = await api().pick_library()
        if (r && r.ok && r.path) setV('st-lib', r.path)
        else if (r && r.msg) { const m = document.getElementById('st-msg'); if (m) m.textContent = r.msg }
    }
    const open = document.getElementById('st-open')
    if (open) open.onclick = async () => {
        if (!api() || !api().open_library) return
        const r = await api().open_library()
        if (r && !r.ok) { const m = document.getElementById('st-msg'); if (m) m.textContent = r.msg || '打不开' }
    }
    const reset = document.getElementById('st-reset-lib')
    if (reset) reset.onclick = () => {
        setV('st-lib', '')
        const m = document.getElementById('st-msg')
        if (m) m.textContent = '已填回默认路径，点「保存」生效'
    }
    const cpick = document.getElementById('st-chrome-pick')
    if (cpick) cpick.onclick = async () => {
        if (!api() || !api().pick_browser) return
        const r = await api().pick_browser()
        if (r && r.ok && r.path) setV('st-chrome', r.path)
    }
    // 实际用的浏览器 / 构建版本：只显示探测结果，不写进配置（发行包不泄漏本机路径）
    const actual = document.getElementById('st-browser-actual')
    if (actual && api() && api().get_submit_status) {
        api().get_submit_status().then(s => {
            if (!s) return
            const b = (s.browser || '').split(/[\\/]/).pop()
            const SRC = { settings: '手动指定', env: '环境变量', system: '系统浏览器',
                          registry: '系统浏览器', bundled: '包内浏览器' }
            actual.textContent = (b
                ? `实际使用：${b}${s.browser_version ? ' · ' + s.browser_version : ''}`
                  + `（${SRC[s.browser_source] || '自动'}）`
                : '实际使用：还没启动过浏览器')
                + `${s.browser_note ? ' · ' + s.browser_note : ''}`
                + ` · 程序 ${s.app_build || ''} · 脚本 build ${s.submit_build || ''}`
        }).catch(() => {})
    }
    const openv = document.getElementById('st-open-verify')
    if (openv) openv.onclick = async () => {
        if (!api() || !api().open_verification_page) return
        const m = document.getElementById('st-msg')
        if (m) m.textContent = '正在打开验证页面…'
        const r = await api().open_verification_page()
        if (m) m.textContent = (r && r.msg) || (r && r.ok ? '已打开' : '打不开')
    }
    ;['st-bad-thresh', 'st-bad-g-severe'].forEach(id => {
        const el = document.getElementById(id)
        if (el) el.oninput = paintBadCounts
    })
    const save = document.getElementById('st-save')
    if (save) save.onclick = saveSettings
}

async function initLibrary() {
    try {
        const r = await fetch('coach/index.json', { cache: 'no-store' })
        COACH_IDX = r.ok ? await r.json() : []
    } catch (e) { COACH_IDX = [] }
    const home = document.getElementById('btn-home')
    if (home) home.onclick = () => { location.href = homeUrl() }
    const go = document.getElementById('link-go')
    const inp = document.getElementById('link-input')
    if (go) go.onclick = submitLink
    if (inp) inp.onkeydown = e => { if (e.key === 'Enter') submitLink() }
    wireSubmitActions()
    const fmtSel = document.getElementById('fmt-select')
    if (fmtSel && inp) {
        const syncHint = () => { inp.placeholder = fmtHint(fmtSel.value) }
        fmtSel.onchange = syncHint
        syncHint()
    }
    const st = document.getElementById('link-status')
    await initSettings()
    await loadUiCfg()          // 先拿配置：教程是否已读、恶手分级阈值
    initWelcome()
    await waitBridge()
    if (st && !hasBridge()) {
        st.textContent = '浏览器模式：分析牌谱需在桌面版使用'
    }
    // 启动自检：缺运行时就直接说清楚，别等点了「分析」才失败
    if (hasBridge() && window.pywebview.api.env_report) {
        try {
            const env = await window.pywebview.api.env_report()
            if (env && env.problems && env.problems.length && st) {
                st.className = 'link-status bad'
                st.textContent = '依赖不全：' + env.problems.join('；')
            }
        } catch (e) { console.warn('env_report', e) }
    }
    setHomeVisibility(isHomeView())
    await loadHistory()
    // 年 / 月 变化时先重建下级选项（没牌谱的月日不会留在下拉里），再筛列表
    ;['history-year', 'history-month'].forEach(id => {
        const el = document.getElementById(id)
        if (el) el.onchange = () => { syncDateSelects(); renderHistory() }
    })
    const dSel = document.getElementById('history-day')
    if (dSel) dSel.onchange = renderHistory
    const selectedTag = tagFallback()
    if (!isHomeView() && selectedTag) await loadCoach(selectedTag)
    // 本局没有恶手时明确说明，避免误以为解读生成失败
    if (!isHomeView() && COACH && COACH.moves && !Object.keys(COACH.moves).length) {
        const body = document.getElementById('cp-body')
        if (body) body.innerHTML = '<span class="cp-empty">本局没有超过 10pt 阈值的恶手，逐手都跟 Mortal 基本一致。</span>'
    }
    if (!isHomeView()) { renderRating(); renderCoach() }
}

function tagFallback() {
    const t = curTag()
    if (t) return t
    return ''
}

function fmtHint(f) {
    return {
        'auto': '牌谱链接 / 对局 ID',
        'log-url': '雀魂 / 天凤牌谱链接',
        'riichi-city-log-id': '一番街对局 ID，如 ch35u1e9nc70954ah9n0@3',
        'hime-mahjong-log-id': '姬麻将对局 ID，如 2907202_6598…',
        'tenhou6': '天凤6 的 JSON 文本',
    }[f] || '牌谱链接 / 对局 ID'
}

async function waitCoach(tag, tries = 10) {
    for (let i = 0; i < tries; i++) {
        try {
            const r = await fetch(`coach/${tag}.json`, { cache: 'no-store' })
            if (r.ok) {
                const d = await r.json()
                if (d && d.game) return d
            }
        } catch (e) { console.warn('coach 轮询', e) }
        await new Promise(res => setTimeout(res, 1000))
    }
    return null
}

// ---- 提交流程：实时阶段 + 人工验证可续 ----
const SUBMIT_STAGE_CN = {
    STARTING: '正在启动浏览器',
    BROWSER_STARTING: '正在启动浏览器',
    CHECKING_VERIFICATION: '正在等待网站自动验证（迟迟不动可点「显示验证窗口」）',
    AWAITING_VERIFICATION: '请在浏览器窗口里勾选「我是人类」',
    VERIFICATION_FAILED: '验证没通过：可点「重新加载验证」再试，或改用普通浏览器生成报告',
    SUBMITTING: '正在提交到 Mortal',
    SCORING: 'Mortal 正在评分',
    DOWNLOADING: '正在下载报告',
    SUBMIT_REJECTED: 'Mortal 拒绝了这个牌谱',
    CANCELLED: '已取消',
}
let SUBMIT_POLL = 0

function submitActions(show) {
    const bar = document.getElementById('submit-actions')
    if (bar) bar.hidden = !show
}

function submissionBusy(busy) {
    for (const id of ['link-go', 'sb-resume', 'sb-retry', 'sb-official']) {
        const el = document.getElementById(id)
        if (el) el.disabled = busy
    }
}

function stopSubmitPoll() {
    if (SUBMIT_POLL) { clearInterval(SUBMIT_POLL); SUBMIT_POLL = 0 }
}

// Promise 还没返回时也要能看到卡在哪一步：以前「请点验证码」这种提示
// 要等整个流程结束才出现，等看到的时候人早就错过了能点的时机。
function startSubmitPoll(st, head) {
    stopSubmitPoll()
    const api = (window.pywebview || {}).api || {}
    if (!api.get_submit_status) return
    SUBMIT_POLL = setInterval(async () => {
        let s = null
        try { s = await api.get_submit_status() } catch (e) { return }
        if (!s || !s.active) return
        const label = SUBMIT_STAGE_CN[s.stage] || s.stage || '处理中'
        let txt = `${head} … ${label}`
        if (s.wait) txt += ` · 已等 ${s.wait}s`
        if (s.detail) txt += `（${s.detail}）`
        const wait = ['AWAITING_VERIFICATION', 'VERIFICATION_FAILED'].includes(s.stage)
        st.className = 'link-status ' + (wait ? 'warn' : 'busy')
        st.textContent = txt
        submitActions(wait)
        const retry = document.getElementById('sb-retry')
        if (retry) retry.disabled = !wait || s.stage === 'VERIFICATION_FAILED'
    }, 1000)
}

async function openReport(tag) {
    const coach = await waitCoach(tag)
    const st = document.getElementById('link-status')
    if (!coach) {
        if (st) {
            st.className = 'link-status warn'
            st.textContent = '报告已下载，但解读文件还没读到；重新打开本局即可（文件已落盘）。'
        }
    }
    let q = '?data=' + encodeURIComponent('report/' + tag + '.json')
    const first = coach && coach.moves ? Object.keys(coach.moves)[0] : ''
    if (first && first.indexOf(':') > 0) {
        const [hh, pp] = first.split(':')
        q += `&hand=${hh}&ply=${pp}`
    }
    location.href = location.pathname + q
}

// 统一的收尾：verification_pending 不是失败，只是还没做完
async function applySubmitResult(r, st) {
    if (!r) { st.className = 'link-status bad'; st.textContent = '没有返回结果'; return }
    if (r.status === 'verification_pending' || r.status === 'verification_failed') {
        st.className = 'link-status warn'
        st.textContent = (r.msg || '请在浏览器窗口里勾选「我是人类」，通过后会自动继续')
            + (r.tag ? `　（标签 ${r.tag}）` : '')
        submitActions(true)
        return
    }
    submitActions(false)
    if (!r.ok) {
        const partial = r.status === 'partial'
        st.className = 'link-status ' + (partial ? 'warn' : 'bad')
        st.textContent = (partial ? '部分完成' : '失败')
            + (r.stage ? `（阶段 ${r.stage}）` : '') + '：' + (r.msg || '未知错误')
        if (r.tag) {
            await initLibrary()
            if (partial) st.textContent += '　报告已下载，可以直接打开这一局。'
        }
        return
    }
    st.textContent = '解读已生成，正在打开…'
    await initLibrary()
    await openReport(r.tag)
}

async function submitLink() {
    const inp = document.getElementById('link-input')
    const st = document.getElementById('link-status')
    const go = document.getElementById('link-go')
    if (!inp || !st) return
    const url = (inp.value || '').trim()
    if (!url) { st.className = 'link-status bad'; st.textContent = '先粘贴牌谱链接或对局 ID'; return }
    if (url.length < 8) { st.className = 'link-status bad'; st.textContent = '内容太短，不像牌谱'; return }
    if (!(window.pywebview && window.pywebview.api && window.pywebview.api.submit_link)) {
        st.className = 'link-status bad'
        st.textContent = '桌面版才支持直接分析牌谱'
        return
    }
    const fmt = (document.getElementById('fmt-select') || {}).value || 'auto'
    const model = (document.getElementById('model-select') || {}).value || '4.1b'
    const seat = (document.getElementById('seat-select') || {}).value || ''
    st.className = 'link-status busy'
    st.textContent = `提交 Mortal（${model}）… 正在启动浏览器`
    submissionBusy(true)
    submitActions(false)
    startSubmitPoll(st, `提交 Mortal（${model}）`)
    try {
        const r = await window.pywebview.api.submit_link(url, fmt, model, seat)
        stopSubmitPoll()
        await applySubmitResult(r, st)
    } catch (e) {
        st.className = 'link-status bad'
        st.textContent = '出错：' + ((e && e.message) || e)
    } finally {
        stopSubmitPoll()
        submissionBusy(false)
    }
}

// 继续等待：同一浏览器、同一页面，不重新开始
async function resumeSubmit(reload = false) {
    const st = document.getElementById('link-status')
    if (!st) return
    const api = (window.pywebview || {}).api || {}
    const fn = reload ? api.retry_verification : api.resume_submit
    if (!fn) return
    submissionBusy(true)
    st.className = 'link-status busy'
    st.textContent = reload ? '重新加载验证页面…' : '继续等待验证…'
    startSubmitPoll(st, '继续等待验证')
    try {
        const r = await fn()
        stopSubmitPoll()
        await applySubmitResult(r, st)
    } catch (e) {
        st.className = 'link-status bad'
        st.textContent = '出错：' + ((e && e.message) || e)
    } finally {
        stopSubmitPoll()
        submissionBusy(false)
    }
}

function wireSubmitActions() {
    const st = document.getElementById('link-status')
    const api = () => (window.pywebview || {}).api || {}
    const show = document.getElementById('sb-show')
    const resume = document.getElementById('sb-resume')
    const cancel = document.getElementById('sb-cancel')
    if (show) show.onclick = async () => {
        const fn = api().show_verification_browser
        if (!fn) return
        const r = await fn()
        if (st && r) { st.className = 'link-status ' + (r.ok ? 'busy' : 'bad'); st.textContent = r.msg || '' }
    }
    if (resume) resume.onclick = () => resumeSubmit(false)
    const retry = document.getElementById('sb-retry')
    if (retry) retry.onclick = async () => {
        const s = await api().get_submit_status()
        if (!s.active) return resumeSubmit(true)
        retry.disabled = true
        const r = await api().request_verification_reload()
        if (st) { st.className = 'link-status warn'; st.textContent = r.msg || '' }
    }
    const official = document.getElementById('sb-official')
    if (official) official.onclick = async () => {
        const fn = api().open_official_review
        if (!fn) return
        submissionBusy(true)
        try {
            const r = await fn((document.getElementById('link-input') || {}).value || '')
            if (r.ok) { stopSubmitPoll(); submitActions(false) }
            if (st) { st.className = 'link-status ' + (r.ok ? 'warn' : 'bad'); st.textContent = r.msg || '' }
        } finally { submissionBusy(false) }
    }
    if (cancel) cancel.onclick = async () => {
        const fn = api().cancel_submit
        if (fn) await fn()
        stopSubmitPoll()
        submitActions(false)
        if (st) { st.className = 'link-status'; st.textContent = '已取消这次提交' }
    }
}


const GS = new GlobalState
// 调试用：控制台执行 MCDEBUG() 可看解读数据与恶手标记的挂载情况
window.MCDEBUG = () => ({
    coachNull: COACH === null,
    coachKeys: COACH ? Object.keys(COACH) : null,
    coachMoves: COACH && COACH.moves ? Object.keys(COACH.moves).length : 0,
    navBuilt: !!NAV,
    navHands: NAV ? NAV.length : 0,
    badPerHand: Object.fromEntries(Object.entries(NAV_BAD).map(([k, v]) => [k, [...v.keys()]])),
})
export default { main, GS, debugState } // So we can access these from dev console
function main() {
    // 本应用的界面固定为简体中文（不再读 localStorage 里的旧语言设置）
    const lang = "zh-CN"
    localStorage.setItem("lang", lang)
    // 先定界面模式，避免主页/牌桌闪一下再切
    const hv = document.getElementById('home-view')
    if (hv) hv.style.display = isHomeView() ? '' : 'none'
    document.body.classList.toggle('home-mode', isHomeView())
    GS.showDealinRate = ("showDealinRate" in localStorage) ? localStorage.getItem("showDealinRate") : false
    GS.errorThreshold = ("errorThreshold" in localStorage) ? localStorage.getItem("errorThreshold") : 1
    i18next_data.lng = lang
    i18next.init(i18next_data).then(() => {
        parseUrl(true)
        initLibrary()
    })
}
main()

