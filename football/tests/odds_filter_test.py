"""Teste pentru excluderea meciurilor cu cota Peste 2.5 > 2.00 (2026-10-09:
doar 3 din 15 au iesit Peste) si pentru marcarea "void" a pick-urilor
blocate pe "pending". Ruleaza: cd football && python -m unittest tests.odds_filter_test"""
from __future__ import annotations

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import check_results  # noqa: E402
import daily_recommendations as dr  # noqa: E402

B, S = dr._SUFFIX_BET, dr._SUFFIX_SB


def _match(home, away, odds):
    return {"Home Team" + B: home, "Away Team" + B: away, "League" + B: "L",
            "Odds Over" + S: odds, "_kickoff_local" + S: "20:00"}


class OddsFilterTests(unittest.TestCase):
    def setUp(self):
        self.matched = pd.DataFrame([_match("A", "B", "1.55"), _match("C", "D", "2.35"), _match("E", "F", "2.00")])

    def test_split(self):
        picks, excluded = dr.split_by_odds(self.matched)
        self.assertEqual(list(picks["Home Team" + B]), ["A", "E"])  # 2.00 inclusiv ramane
        self.assertEqual(list(excluded["Home Team" + B]), ["C"])

    def test_email_lists_excluded_separately(self):
        picks, excluded = dr.split_by_odds(self.matched)
        body = dr.build_email_body(picks, 0, "2026-10-09", excluded)
        self.assertEqual(body.count("<h3"), 2)
        self.assertIn("Excluse", body)
        self.assertIn("C vs D (cota 2.35)", body)

    def test_excluded_are_logged_with_flag(self):
        picks, excluded = dr.split_by_odds(self.matched)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(dr, "LOG_PATH", str(Path(tmp) / "log.csv")):
            dr.log_todays_picks(picks, "2026-10-09")
            dr.log_todays_picks(excluded, "2026-10-09", excluded="odds>2.0")
            log = pd.read_csv(dr.LOG_PATH, dtype=str, keep_default_na=False)
        self.assertEqual(dict(zip(log["home_team"], log["excluded"])), {"A": "", "E": "", "C": "odds>2.0"})


class StalePendingTests(unittest.TestCase):
    def test_old_pending_becomes_void(self):
        old = (dt.date.today() - dt.timedelta(days=6)).isoformat()
        recent = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        rows = [{"date": old, "home_team": "A", "away_team": "B", "result": "pending"},
                {"date": recent, "home_team": "C", "away_team": "D", "result": "pending"}]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(check_results, "LOG_PATH", str(Path(tmp) / "log.csv")), \
                mock.patch.object(check_results, "scrape_bet_date", return_value=None), \
                mock.patch.object(sys, "argv", ["check_results.py"]):
            pd.DataFrame(rows).to_csv(check_results.LOG_PATH, index=False)
            check_results.main()
            out = pd.read_csv(check_results.LOG_PATH, dtype=str)
        self.assertEqual(list(out["result"]), ["void", "pending"])


if __name__ == "__main__":
    unittest.main()
