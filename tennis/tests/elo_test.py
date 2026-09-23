"""Teste offline pentru history.py (pe HTML real din tests/fixtures/) si
elo.py. Ruleaza: cd tennis && python -m unittest tests.elo_test"""
from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import elo  # noqa: E402
import history  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class HistoryParsingTests(unittest.TestCase):
    def test_results_page_keeps_only_completed_singles(self):
        html = (FIXTURES / "results_wta_2026-09-21.html").read_text(encoding="utf-8")
        matches = history.parse_results_page(html, dt.date(2026, 9, 21), "wta-single")
        self.assertEqual(len(matches), 152)  # 162 meciuri, minus 10 walkover-uri / abandonuri
        first = matches[0]
        self.assertEqual(
            (first.winner_slug, first.loser_slug, first.score, first.odds_winner, first.odds_loser, first.tournament_slug),
            ("/player/garland-472f9/", "/player/hunter-575cb/", "6-3 5-7 6-1", 1.73, 2.08, "/singapore-wta/2026/wta-women/"),
        )
        self.assertTrue(all(len(m.score.split()) in (2, 3) for m in matches))

    def test_tournament_surface(self):
        html = (FIXTURES / "tournament_chengdu.html").read_text(encoding="utf-8")
        self.assertEqual(history.parse_tournament_surface(html), "Hard")


def _match(date, winner, loser, surface="Hard", odds_w=None, odds_l=None, match_id=0):
    return {"date": date, "match_id": match_id, "tour_type": "atp-single", "tournament": "T",
            "tournament_slug": "/t/", "winner_slug": winner, "loser_slug": loser,
            "winner_name": winner, "loser_name": loser, "score": "6-4 6-4",
            "odds_winner": odds_w, "odds_loser": odds_l, "surface": surface}


class EloTests(unittest.TestCase):
    def test_expected_is_symmetric(self):
        self.assertAlmostEqual(elo.expected(1600, 1500) + elo.expected(1500, 1600), 1.0)
        self.assertAlmostEqual(elo.expected(1500, 1500), 0.5)

    def test_new_players_move_more(self):
        self.assertGreater(elo.k_factor(0), elo.k_factor(50))

    def test_prediction_uses_only_earlier_matches(self):
        matches = pd.DataFrame([
            _match("2026-09-01", "A", "B", match_id=1),
            _match("2026-09-02", "A", "B", match_id=2),
        ])
        _, df = elo.run(matches, eval_from="2026-09-01")
        self.assertAlmostEqual(df.iloc[0]["p_blend"], 0.5)  # primul meci: nimic stiut inainte
        self.assertGreater(df.iloc[1]["p_blend"], 0.5)      # al doilea: A a castigat primul

    def test_surface_rating_is_separate(self):
        book = elo.EloBook()
        for _ in range(10):
            book.update("A", "B", "Clay")
        on_clay, on_grass = book.predict("A", "B", "Clay"), book.predict("A", "B", "Grass")
        self.assertGreater(on_clay["surface"], 0.9)
        self.assertAlmostEqual(on_grass["surface"], 0.5)
        self.assertGreater(on_clay["blend"], on_grass["blend"])

    def test_betting_simulation_uses_real_odds(self):
        df = pd.DataFrame([
            # Elo il vede pe castigator mult mai bun decat piata -> pariu castigat la 3.0
            {"p_blend": 0.6, "p_market": 0.35, "odds_winner": 3.0, "odds_loser": 1.4},
            # Elo il vede pe invins mult mai bun -> pariu pierdut
            {"p_blend": 0.3, "p_market": 0.6, "odds_winner": 1.6, "odds_loser": 2.4},
            # fara diferenta -> fara pariu
            {"p_blend": 0.5, "p_market": 0.5, "odds_winner": 1.9, "odds_loser": 1.9},
        ])
        b = elo.betting_simulation(df, "p_blend", 0.10)
        self.assertEqual((b["bets"], b["won"], b["profit"]), (2, 1, 1.0))


if __name__ == "__main__":
    unittest.main()
