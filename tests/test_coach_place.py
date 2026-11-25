# -*- coding: utf-8 -*-
"""最终顺位（历史列表日期后面那个「N位」）的计算单测。

跑法：
    runtime\\python\\python.exe -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "scripts"))
import gamescore  # noqa: E402


def kyoku(scores, oya=0):
    return {"type": "start_kyoku", "scores": list(scores), "oya": oya}


class FinalPlace(unittest.TestCase):
    def test_basic_ranking(self):
        """点和后按点数排名，自己的名次与点数都要对。"""
        rep = {"player_id": 1, "mjai_log": [
            kyoku([25000] * 4),
            {"type": "hora", "deltas": [8000, -4000, -2000, -2000]},
        ]}
        place, score = gamescore.final_place(rep)
        self.assertEqual(score, 21000)
        self.assertEqual(place, 4)

    def test_reach_stick_is_deducted(self):
        """立直棒不在 deltas 里：不先扣 1000，和牌者会凭空多出供托那 1000。"""
        rep = {"player_id": 0, "mjai_log": [
            kyoku([25000] * 4),
            {"type": "reach_accepted", "actor": 0},
            {"type": "hora", "deltas": [5000, -2500, -2500, 0]},
        ]}
        place, score = gamescore.final_place(rep)
        self.assertEqual(score, 29000)      # 25000 - 1000 + 5000
        self.assertEqual(place, 1)

    def test_tie_breaks_by_oya_order(self):
        """同点时按起家顺序定先后。"""
        rep = {"player_id": 3, "mjai_log": [kyoku([25000] * 4, oya=0)]}
        self.assertEqual(gamescore.final_place(rep)[0], 4)
        rep = {"player_id": 0, "mjai_log": [kyoku([25000] * 4, oya=2)]}
        self.assertEqual(gamescore.final_place(rep)[0], 3)   # 起家 2 在前，0 排第三

    def test_later_kyoku_scores_win(self):
        """每局 start_kyoku 的 scores 已含前面结算，以最后一次为准。"""
        rep = {"player_id": 2, "mjai_log": [
            kyoku([25000] * 4),
            {"type": "hora", "deltas": [12000, -4000, -4000, -4000]},
            kyoku([37000, 21000, 21000, 21000]),
            {"type": "hora", "deltas": [-6000, 2000, 2000, 2000]},
        ]}
        place, score = gamescore.final_place(rep)
        self.assertEqual(score, 23000)
        self.assertEqual(place, 3)          # 三家同为 23000，按起家顺序排 1/2/3

    def test_missing_data_returns_none(self):
        self.assertEqual(gamescore.final_place({}), (None, None))
        self.assertEqual(gamescore.final_place({"mjai_log": [], "player_id": 0}), (None, None))
        rep = {"player_id": 9, "mjai_log": [kyoku([25000] * 4)]}
        self.assertEqual(gamescore.final_place(rep), (None, None))

    def test_mk_coach_writes_place_into_index(self):
        """索引里要有 place 字段，前端才画得出徽章。"""
        src = (BASE / "scripts" / "mk_coach.py").read_text(encoding="utf-8")
        self.assertIn("from gamescore import final_place", src)
        self.assertIn('"place": place', src)
        js = (BASE / "assets" / "kd" / "index.js").read_text(encoding="utf-8")
        self.assertIn("hr-place", js)


if __name__ == "__main__":
    unittest.main()
