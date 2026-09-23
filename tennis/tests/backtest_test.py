"""Teste offline pentru backtest.py, pe HTML real din tests/fixtures/.
Ruleaza: cd tennis && python -m unittest tests.backtest_test"""
from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backtest  # noqa: E402
from tenis_scraper import tennisexplorer as te  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class ResultsPageTests(unittest.TestCase):
    def test_parses_real_results_page(self):
        html = (FIXTURES / "results_wta_2026-09-21.html").read_text(encoding="utf-8")
        rows = backtest.parse_results_page(html, dt.date(2026, 9, 21), "wta-single")
        self.assertEqual(len(rows), 162)
        self.assertEqual((rows[0].tournament, rows[0].match_id, rows[0].odds_first, rows[0].odds_second),
                         ("Singapore WTA", 3328395, 1.73, 2.08))


class PreMatchSignalsTests(unittest.TestCase):
    def setUp(self):
        html = (FIXTURES / "match_baez_brooksby.html").read_text(encoding="utf-8")
        self.detail = te.parse_match_detail(html)
        self.signals = backtest.pre_match_signals(self.detail, 3329361, dt.date(2026, 9, 23))

    def test_outcome_and_no_leak_from_the_match_itself(self):
        s = self.signals
        self.assertEqual(s["p1_won"], 1)  # Brooksby, player1 pe pagina
        # H2H fara Chengdu: Baez 2-0 -> Brooksby sub 50%
        self.assertLess(s["h2h_p"], 0.5)
        # pe hard, Brooksby 9/11 si Baez 16/10 includ Chengdu -> 8/11 si 16/9 inainte de meci
        balance = backtest._subtract_match_from_balance(self.detail.surface_balance, "Hard", True)
        self.assertEqual(balance["Hard"], ("8/11", "16/9"))

    def test_flip_is_symmetric(self):
        flipped = backtest.flip_perspective(self.signals)
        self.assertEqual(flipped["p1_won"], 0)
        self.assertAlmostEqual(flipped["model_new"], 1 - self.signals["model_new"])
        back = backtest.flip_perspective(flipped)
        for key, value in self.signals.items():
            if isinstance(value, float):
                self.assertAlmostEqual(back[key], value)
            else:
                self.assertEqual(back[key], value)

    def test_unplayed_match_is_skipped(self):
        html = (FIXTURES / "match_arifullina_ruchkina.html").read_text(encoding="utf-8")
        detail = te.parse_match_detail(html)
        self.assertIsNone(backtest.pre_match_signals(detail, 3331278, dt.date(2026, 9, 23)))


class LogisticTests(unittest.TestCase):
    def test_learns_positive_weight_for_informative_signal(self):
        rng = np.random.default_rng(0)
        p = rng.uniform(0.2, 0.8, 800)
        y = (rng.uniform(size=800) < p).astype(int)
        df = pd.DataFrame({"rank_p": p, "form_new_p": 0.5, "surface_p": None, "h2h_p": None,
                           "fatigue_pp": 0.0, "p1_won": y})
        weights = backtest.fit_logistic(df)
        self.assertGreater(weights["rank_p"], 0.5)
        self.assertAlmostEqual(weights["form_new_p"], 0.0, places=6)


if __name__ == "__main__":
    unittest.main()
