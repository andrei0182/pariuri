"""Teste pentru analiza pe istoricul jucatorilor (player_history.py).
Ruleaza fara retea: cd tennis && python -m unittest tests.player_history_test"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import player_history as ph  # noqa: E402


def _match(i, winner, loser, score, surface="Hard", tournament="Wuhan"):
    return {"date": f"2026-09-{1 + i // 10:02d}", "match_id": i, "winner_slug": winner, "loser_slug": loser,
            "winner_name": winner, "loser_name": loser, "score": score, "surface": surface,
            "tournament": tournament, "tour_type": "wta-single", "tournament_slug": "/x/",
            "odds_winner": None, "odds_loser": None}


def _history():
    """A castiga clar pe hard (si cu adversarii comuni C, D); B pierde des."""
    rows, i = [], 0
    for _ in range(6):
        for opp in ("/c/", "/d/"):
            rows.append(_match(i, "/a/", opp, "6-2 6-3")); i += 1
            rows.append(_match(i, opp, "/b/", "6-3 6-4")); i += 1
    rows.append(_match(i, "/a/", "/b/", "6-4 6-4"))
    return ph.build_history(pd.DataFrame(rows))


def _report(odds_a=1.6, odds_b=2.3):
    return pd.DataFrame([{
        ph._P1: "Bea B", ph._P2: "Ana A", ph._ODDS[1]: odds_b, ph._ODDS[2]: odds_a,
        ph._SLUG[1]: "/b/", ph._SLUG[2]: "/a/", ph._SURFACE: "hard", ph._TOUR: "wta",
        ph._TOURNAMENT: "Wuhan", ph._TIME: "2026-10-11 04:30:00", ph._TE_ID: 123,
        ph._LINES[1]: "5.5@1.5", ph._LINES[2]: "8.5@1.4; 9.5@1.6",
    }])


class PlayerHistoryTests(unittest.TestCase):
    def setUp(self):
        self.h = _history()

    def test_all_indicators_agree(self):
        a = ph.analyze(_report(), self.h)
        row = a.iloc[0]
        self.assertEqual(row.recommended_player, "Ana A")
        self.assertEqual(row.verdict, ph.AGREE)
        self.assertTrue(row.odds_pass)
        self.assertEqual(row.games_odds, 1.4)
        self.assertEqual(row.time, "07:30")  # UTC -> ora Romaniei
        self.assertIn("H2H 1-0", row.details)
        self.assertIn("adversari comuni (2) +100%", row.details)

    def test_odds_below_threshold_not_in_recommendations(self):
        a = ph.analyze(_report(odds_a=1.2), self.h)
        self.assertFalse(a.iloc[0].odds_pass)
        html = ph.email_section_html(a)
        self.assertIn("Toti indicatorii de acord (0)", html)
        self.assertIn("cota sub 1.5: Ana A @ 1.2", html)

    def test_h2h_against_downgrades_verdict(self):
        h = self.h
        h.vs["/a/"]["/b/"] = [0, 3]
        h.vs["/b/"]["/a/"] = [3, 0]
        self.assertNotEqual(ph.assess(h, "/a/", "/b/", "Hard")["verdict"], ph.AGREE)

    def test_without_surface_history_skipped(self):
        report = _report()
        report[ph._SURFACE] = "clay"
        self.assertTrue(ph.analyze(report, self.h).empty)

    def test_log_picks_no_duplicates(self):
        a = ph.analyze(_report(), self.h)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ph, "LOG_PATH", Path(tmp) / "log.csv"):
            ph.log_picks(a, "2026-10-11")
            ph.log_picks(a, "2026-10-11")
            log = pd.read_csv(ph.LOG_PATH, dtype=str)
        self.assertEqual(len(log), 1)
        self.assertEqual(log.loc[0, "result"], "pending")
        self.assertEqual(log.loc[0, "games_line"], "8.5")
        self.assertEqual(list(log.columns), ph.LOG_COLUMNS)

    def test_summary_counts_only_odds_pass(self):
        log = pd.DataFrame([
            {"verdict": ph.AGREE, "odds_pass": "True", "result": "won", "rec_odds": "1.61"},
            {"verdict": ph.AGREE, "odds_pass": "True", "result": "lost", "rec_odds": "1.78"},
            {"verdict": ph.AGREE, "odds_pass": "False", "result": "won", "rec_odds": "1.2"},
        ])
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ph, "LOG_PATH", Path(tmp) / "log.csv"):
            log.to_csv(ph.LOG_PATH, index=False)
            html = ph.summary_html()
        self.assertIn("toti de acord: 1 din 2 castigate (50%), profit -0.39u", html)


if __name__ == "__main__":
    unittest.main()
