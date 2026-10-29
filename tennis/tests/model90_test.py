"""Teste pentru modelul 90% (model90.py) si rezolvarea "adversarul sub X".
Ruleaza fara retea: cd tennis && python -m unittest tests.model90_test"""
from __future__ import annotations

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import check_results  # noqa: E402
import main  # noqa: E402
import model90 as m  # noqa: E402
from tenis_scraper.tennisexplorer import MatchDetailData, PlayerProfile  # noqa: E402


def _history(n_days=60):
    """Jucatori "/s0/".."/s4/" (puternici) bat mereu "/w0/".."/w9/" (slabi), clar."""
    rng = np.random.default_rng(0)
    rows, mid = [], 0
    start = dt.date(2026, 5, 1)
    for d in range(n_days):
        day = (start + dt.timedelta(days=d)).isoformat()
        for _ in range(6):
            s, w = f"/s{rng.integers(5)}/", f"/w{rng.integers(10)}/"
            rows.append({"date": day, "match_id": mid, "winner_slug": s, "loser_slug": w, "winner_name": s,
                         "loser_name": w, "score": ["6-2 6-1", "6-4 7-5", "7-6 6-4"][rng.integers(3)], "surface": "Hard", "tournament": "Challenger X",
                         "tour_type": "atp-single", "tournament_slug": "/x/", "odds_winner": 1.2, "odds_loser": 4.0})
            mid += 1
    return pd.DataFrame(rows)


class Model90Tests(unittest.TestCase):
    def test_labels_match_report_columns(self):
        self.assertEqual(main._COLUMN_LABELS["p1_games_under"], m._UNDER[1])
        self.assertEqual(main._COLUMN_LABELS["p2_games_under"], m._UNDER[2])

    def test_features_use_only_prior_matches(self):
        state, rows = m.build(_history(3))
        first = rows.iloc[0]
        self.assertEqual(first.n_x, 0)        # primul meci: nimic inainte
        self.assertTrue(np.isnan(first.f5_x))
        self.assertEqual(set(m.FEATURES) - set(rows.columns), set())

    def test_train_predict_and_log(self):
        state, rows = m.build(_history())
        models = {t: m.train(rows, t) for t in m.MARKETS}
        self.assertIsNotNone(models[m.TARGET_WIN].threshold)
        report = pd.DataFrame([{
            m._P1: "Slab", m._P2: "Tare", m._ODDS[1]: 4.0, m._ODDS[2]: 1.2,
            m._SLUG[1]: "/w1/", m._SLUG[2]: "/s1/", m._SURFACE: "hard", m._TOUR: "challenger",
            m._TOURNAMENT: "X", m._TIME: "2026-07-01 10:00:00", m._TE_ID: 7,
            m._UNDER[1]: "5.5@1.9; 6.5@1.55", m._UNDER[2]: "",
        }])
        picks = m.predict(report, state, models, dt.date(2026, 7, 1))
        win = picks[picks.market == m.MARKETS[m.TARGET_WIN]]
        self.assertEqual(list(win.recommended_player), ["Tare"])
        opp = picks[picks.market == m.MARKETS[m.TARGET_OPP_UNDER]]
        if not opp.empty:  # cota Sub 6.5 a ADVERSARULUI (J1)
            self.assertEqual(opp.iloc[0].games_odds, 1.55)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(m, "LOG_PATH", Path(tmp) / "l.csv"):
            m.log_picks(picks, "2026-07-01")
            m.log_picks(picks, "2026-07-01")
            log = pd.read_csv(m.LOG_PATH, dtype=str)
        self.assertEqual(len(log), len(picks))
        self.assertEqual(list(log.columns), m.LOG_COLUMNS)

    def test_filters_unknown_opponent_and_high_odds(self):
        state, rows = m.build(_history())
        models = {t: m.train(rows, t) for t in m.MARKETS}
        base = {m._P1: "Slab", m._P2: "Tare", m._ODDS[1]: 4.0, m._ODDS[2]: 1.2,
                m._SLUG[1]: "/w1/", m._SLUG[2]: "/s1/", m._SURFACE: "hard", m._TOUR: "challenger",
                m._TOURNAMENT: "X", m._TIME: "2026-07-01 10:00:00", m._TE_ID: 7}
        unknown = dict(base, **{m._P1: "Nou", m._SLUG[1]: "/nou/"})      # adversar fara niciun meci
        high = dict(base, **{m._ODDS[2]: m.MAX_PICK_ODDS + 0.5})          # piata il vede outsider
        day = dt.date(2026, 7, 1)
        self.assertIn("Tare", list(m.predict(pd.DataFrame([base]), state, models, day).recommended_player))
        for row in (unknown, high):
            picks = m.predict(pd.DataFrame([row]), state, models, day)
            self.assertNotIn("Tare", list(picks.recommended_player) if not picks.empty else [])

    def test_resolve_opponent_under(self):
        detail = MatchDetailData(player1=PlayerProfile(name="Tare Ana"), player2=PlayerProfile(name="Slab Bob"),
                                 set_scores=[(6, 3), (6, 2)], retired=False)
        row = pd.Series({"recommended_player": "Ana Tare", "opponent": "Bob Slab", "games_line": "6.5",
                         "games_bet": "opp_under"})
        self.assertEqual(check_results.resolve_games(row, detail)[0], "won")      # adversar 5 game-uri
        detail.set_scores = [(6, 4), (7, 5)]
        self.assertEqual(check_results.resolve_games(row, detail)[0], "lost")     # adversar 9
        row["games_bet"] = "over"
        self.assertEqual(check_results.resolve_games(row, detail)[0], "won")      # jucator 13 > 6.5


if __name__ == "__main__":
    unittest.main()
