"""Teste pentru comparatia Superbet vs media pietei (market_value.py).
Ruleaza fara retea: cd tennis && python -m unittest tests.market_value_test"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402
import market_value as mv  # noqa: E402


def _row(p1, p2, o1, o2, m1, m2):
    return {mv._P1: p1, mv._P2: p2, mv._ODDS[1]: o1, mv._ODDS[2]: o2, mv._MARKET[1]: m1, mv._MARKET[2]: m2,
            mv._TOUR: "atp", mv._TOURNAMENT: "Shanghai", mv._TIME: "2026-10-13 09:00:00", mv._TE_ID: 1}


class MarketValueTests(unittest.TestCase):
    def test_labels_match_report_columns(self):
        self.assertEqual(main._COLUMN_LABELS["te_odds_1"], mv._MARKET[1])
        self.assertEqual(main._COLUMN_LABELS["te_odds_2"], mv._MARKET[2])

    def test_value_found_on_right_side(self):
        df = pd.DataFrame([_row("A", "B", 1.85, 1.95, 1.70, 2.10)])  # A: 1.85/1.70 = +8.8%
        out = mv.find_value(df)
        self.assertEqual(list(out.recommended_player), ["A"])
        self.assertAlmostEqual(out.iloc[0].value_pct, 8.8)
        self.assertEqual(out.iloc[0].time, "12:00")

    def test_filters(self):
        df = pd.DataFrame([
            _row("Mic", "X", 1.84, 2.0, 1.80, 2.0),     # +2% - sub prag
            _row("Lung", "X", 6.0, 1.1, 5.0, 1.15),     # +20%, dar cota > 3.50
            _row("Eroare", "X", 2.8, 1.4, 1.5, 2.5),    # +87% - date stricate
            _row("Fav", "X", 1.25, 4.0, 1.15, 4.5),     # +8.7%, dar cota < 1.30
            _row("Lipsa", "X", 1.9, 1.9, None, None),   # fara cota medie
        ])
        self.assertTrue(mv.find_value(df).empty)

    def test_log_and_summary(self):
        df = pd.DataFrame([_row("A", "B", 1.85, 1.95, 1.70, 2.10)])
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(mv, "LOG_PATH", Path(tmp) / "v.csv"):
            mv.log_value(mv.find_value(df), "2026-10-13")
            mv.log_value(mv.find_value(df), "2026-10-13")
            log = pd.read_csv(mv.LOG_PATH, dtype=str)
            self.assertEqual(len(log), 1)
            self.assertEqual(list(log.columns), mv.LOG_COLUMNS)
            log.loc[0, "result"] = "won"
            log.to_csv(mv.LOG_PATH, index=False)
            html = mv.summary_html()
        self.assertIn("1 din 1 castigate (media pietei astepta ~0.6), profit +0.85u", html)


if __name__ == "__main__":
    unittest.main()
