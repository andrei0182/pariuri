"""Teste pentru comparatia Superbet vs media pietei (market_value.py).
Ruleaza fara retea: cd tennis && python -m unittest tests.market_value_test"""
from __future__ import annotations

import datetime as dt
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


class CheckResultsWithoutGamesLineTests(unittest.TestCase):
    def test_retired_match_in_log_without_games_line(self):
        """2026-10-17: un abandon intr-un log fara coloana games_line oprea check_results."""
        import check_results
        from tenis_scraper.tennisexplorer import MatchDetailData, PlayerProfile, RecentMatch

        detail = MatchDetailData(
            player1=PlayerProfile(name="Fuele Matyas"), player2=PlayerProfile(name="Bilozertsev Nikita"),
            set_scores=[(3, 6), (1, 0)], retired=True,
            player2_recent=[RecentMatch(opponent="Fuele Matyas", won=True, score="1:0")],
        )
        row = {c: "" for c in mv.LOG_COLUMNS} | {
            # data recenta: un rand mai vechi de VOID_AFTER_DAYS ar fi marcat void inainte de verificare
            "date": (dt.date.today() - dt.timedelta(days=1)).isoformat(), "player1": "Matyas Fuele", "player2": "Nikita Bilozertsev",
            "recommended_player": "Nikita Bilozertsev", "opponent": "Matyas Fuele", "te_match_id": "1", "result": "pending"}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v.csv"
            pd.DataFrame([row]).to_csv(path, index=False)
            with mock.patch.object(check_results.tennisexplorer, "fetch_and_parse_match", return_value=detail):
                check_results.check_log(path, mv.LOG_COLUMNS)
            log = pd.read_csv(path, dtype=str)
        self.assertEqual(log.loc[0, "result"], "won")


if __name__ == "__main__":
    unittest.main()
