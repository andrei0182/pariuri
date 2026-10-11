"""Teste pentru ajustarile din 2026-10-09, facute dupa analiza log-urilor:
- linia "Peste X game-uri" a pick-urilor e marcata EXCLUS la liniile 8-9.5
  sau la cota > 1.70 (si nu mai intra in statistica)
- pick-urile fara rezultat dupa 5 zile (walkover, meci negasit) devin "void"
Ruleaza: cd tennis && python -m unittest tests.optimizations_test"""
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
import send_report_email as sre  # noqa: E402
import underdog  # noqa: E402


class GamesExclusionTests(unittest.TestCase):
    def test_reasons(self):
        self.assertEqual(sre.games_exclusion_reason(8.5, 1.55), "linie 8-10")
        self.assertEqual(sre.games_exclusion_reason(9.5, 1.60), "linie 8-10")
        self.assertEqual(sre.games_exclusion_reason(10.0, 1.60), "linie 8-10")
        self.assertEqual(sre.games_exclusion_reason(10.5, 1.75), "cota > 1.70")
        self.assertEqual(sre.games_exclusion_reason(10.5, 1.64), "")
        self.assertEqual(sre.games_exclusion_reason(7.5, 1.70), "")
        self.assertEqual(sre.games_exclusion_reason(None, None), "")

    def test_summary_ignores_excluded_lines(self):
        log = pd.DataFrame([
            {"result": "won", "rec_odds": "2.0", "games_result": "won", "games_odds": "1.6", "games_excluded": ""},
            {"result": "lost", "rec_odds": "2.0", "games_result": "lost", "games_odds": "1.8", "games_excluded": "cota > 1.70"},
        ])
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(sre, "PICKS_LOG_PATH", Path(tmp) / "p.csv"):
            log.to_csv(sre.PICKS_LOG_PATH, index=False)
            html = sre.accuracy_summary_html()
        self.assertIn("din 1 confirmate, 1 castigate", html)

    def test_summary_separates_current_rules(self):
        log = pd.DataFrame([
            {"result": "lost", "rec_odds": "3.0", "rules": ""},
            {"result": "lost", "rec_odds": "2.5", "rules": ""},
            {"result": "won", "rec_odds": "1.5", "rules": sre.RULES_VERSION},
        ])
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(sre, "PICKS_LOG_PATH", Path(tmp) / "p.csv"):
            log.to_csv(sre.PICKS_LOG_PATH, index=False)
            html = sre.accuracy_summary_html()
        self.assertIn("Reguli Elo (de pe 12 oct.):</b> din 1 pick-uri confirmate, 1 au fost castigate (100%), profit +0.50", html)
        self.assertIn("Tot istoricul (include regulile vechi):</b> din 3 pick-uri confirmate", html)


class StaleVoidTests(unittest.TestCase):
    def _run(self, rows, columns):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "log.csv"
            pd.DataFrame(rows).to_csv(path, index=False)
            with mock.patch.object(check_results.tennisexplorer, "fetch_and_parse_match", return_value=None):
                check_results.check_log(path, columns)
            return pd.read_csv(path, dtype=str)

    def test_old_pending_becomes_void_recent_stays(self):
        old = (dt.date.today() - dt.timedelta(days=6)).isoformat()
        recent = (dt.date.today() - dt.timedelta(days=2)).isoformat()
        base = {c: "" for c in check_results.LOG_COLUMNS}
        out = self._run([
            base | {"date": old, "recommended_player": "A B", "te_match_id": "1", "result": "pending"},
            base | {"date": recent, "recommended_player": "C D", "te_match_id": "2", "result": "pending"},
        ], check_results.LOG_COLUMNS)
        self.assertEqual(list(out["result"]), ["void", "pending"])
        self.assertEqual(out.iloc[0]["games_result"], "void")

    def test_underdog_no_data_rows_are_voided(self):
        old = (dt.date.today() - dt.timedelta(days=10)).isoformat()
        base = {c: "" for c in underdog.LOG_COLUMNS}
        out = self._run([base | {"date": old, "recommended_player": "X Y", "result": "no_data"}],
                        underdog.LOG_COLUMNS)
        self.assertEqual((out.iloc[0]["result"], out.iloc[0]["games_result"]), ("void", "void"))


if __name__ == "__main__":
    unittest.main()
