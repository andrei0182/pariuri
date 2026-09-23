"""Teste offline pentru underdog.py (outsideri + pariul "Peste X game-uri")
si pentru legatura cu check_results.py / send_report_email.py.
Ruleaza: cd tennis && python -m unittest tests.underdog_test"""
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
import main  # noqa: E402
import send_report_email as sre  # noqa: E402
import underdog  # noqa: E402
from tenis_scraper import tennisexplorer as te  # noqa: E402
from tenis_scraper.tennisexplorer import MatchDetailData, PlayerProfile  # noqa: E402

L = main._COLUMN_LABELS


def _hist_match(date, winner, loser, score, odds_w, odds_l, tournament="Genoa challenger", mid=0):
    return {"date": date, "match_id": mid, "tour_type": "atp-single", "tournament": tournament,
            "tournament_slug": "/t/", "winner_slug": winner, "loser_slug": loser,
            "winner_name": winner, "loser_name": loser, "score": score,
            "odds_winner": odds_w, "odds_loser": odds_l}


class HistoryTests(unittest.TestCase):
    def test_uses_only_losses_before_each_match(self):
        results = pd.DataFrame([
            _hist_match("2026-09-01", "/player/fav/", "/player/dog/", "6-3 6-2", 1.15, 5.0, mid=1),
            _hist_match("2026-09-02", "/player/fav/", "/player/dog/", "6-1 6-0", 1.15, 5.0, mid=2),
        ])
        h = underdog.build_history(results)
        self.assertEqual(list(h.samples["player_losses"]), [0, 1])       # primul meci: nimic stiut inainte
        self.assertEqual(list(h.samples["dog_games"]), [5, 1])
        self.assertEqual(h.loss_games["/player/dog/"], [5, 1])

    def test_filter(self):
        self.assertTrue(underdog.passes_filter("Challenger/125", 5.0, 6, 0.9))
        self.assertFalse(underdog.passes_filter("ITF", 5.0, 6, 0.9))           # ITF exclus
        self.assertFalse(underdog.passes_filter("ATP/WTA", 8.0, 6, 0.9))       # cota prea mare
        self.assertFalse(underdog.passes_filter("ATP/WTA", 5.0, 4, 1.0))       # prea putine infrangeri
        self.assertFalse(underdog.passes_filter("ATP/WTA", 5.0, 10, 0.8))      # prea putin "rezistent"


class SelectionTests(unittest.TestCase):
    def setUp(self):
        # outsiderul are 6 infrangeri anterioare, toate cu >= 4 game-uri
        rows = [_hist_match(f"2026-08-{i+1:02d}", f"/player/x{i}/", "/player/dog/", "6-4 6-3", 1.2, 4.5, mid=i)
                for i in range(6)]
        self.hist = underdog.build_history(pd.DataFrame(rows))
        self.report = pd.DataFrame([{
            L["tour"]: "challenger", L["tournament"]: "Plovdiv", L["player1"]: "Fav Player",
            L["player2"]: "Dog Player", L["odds_1"]: 1.18, L["odds_2"]: 4.8,
            L["p1_slug"]: "/player/fav/", L["p2_slug"]: "/player/dog/",
            L["p1_games_lines"]: "12.5@1.8", L["p2_games_lines"]: "3.5@1.30; 4.5@1.55; 6.5@2.4",
            L["te_match_id"]: 123,
        }])

    def test_selects_underdog_lines_up_to_5_5(self):
        c = underdog.select_underdogs(self.report, self.hist, L)
        self.assertEqual(list(c["games_line"]), [3.5, 4.5])
        self.assertTrue(c["filter_pass"].all())
        self.assertEqual(set(c["recommended_player"]), {"Dog Player"})
        self.assertAlmostEqual(c.iloc[0]["break_even"], round(1 / 1.30, 3))

    def test_log_does_not_duplicate(self):
        c = underdog.select_underdogs(self.report, self.hist, L)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(underdog, "LOG_PATH", Path(tmp) / "u.csv"):
            underdog.log_underdogs(c, "2026-09-23")
            underdog.log_underdogs(c, "2026-09-23")
            log = pd.read_csv(underdog.LOG_PATH, dtype=str)
        self.assertEqual(len(log), 2)
        self.assertEqual(set(log["games_result"].fillna("")), {""})
        self.assertEqual(set(log["result"]), {"pending"})

    def test_email_section_lists_best_line(self):
        c = underdog.select_underdogs(self.report, self.hist, L)
        html = underdog.email_section_html(c)
        self.assertIn("Dog Player", html)
        self.assertIn("URMĂRIRE PE HÂRTIE", html)
        self.assertEqual(html.count("<li>"), 1)  # o singura linie per jucator


class CheckResultsTests(unittest.TestCase):
    def test_underdog_log_is_settled_and_extra_columns_kept(self):
        detail = MatchDetailData(
            player1=PlayerProfile(name="Favora Maria"), player2=PlayerProfile(name="Dogova Ana"),
            set_scores=[(6, 3), (6, 4)],
        )
        # pe pagina, meciul apare in lista recenta a outsiderului, ca infrangere
        detail.player2_recent = [te.RecentMatch(opponent="Favora-Dogova", score="2:0", won=False)]
        yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        log = pd.DataFrame([{c: "" for c in underdog.LOG_COLUMNS} | {
            "date": yesterday, "recommended_player": "Ana Dogova", "opponent": "Maria Favora",
            "games_line": "4.5", "games_odds": "1.55", "te_match_id": "123", "result": "pending",
            "filter_pass": "True", "dog_odds": "4.8",
        }])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "u.csv"
            log.to_csv(path, index=False)
            with mock.patch.object(check_results.tennisexplorer, "fetch_and_parse_match", return_value=detail):
                check_results.check_log(path, underdog.LOG_COLUMNS)
            out = pd.read_csv(path, dtype=str)
        # Dogova (player2 pe pagina) a facut 3 + 4 = 7 game-uri > 4.5
        self.assertEqual((out.iloc[0]["result"], out.iloc[0]["games_result"], out.iloc[0]["rec_games"]),
                         ("lost", "won", "7"))
        self.assertEqual(out.iloc[0]["dog_odds"], "4.8")


class EmailTests(unittest.TestCase):
    def test_body_includes_underdog_section(self):
        body = sre.build_email_body(pd.DataFrame(), "2026-09-23", "<h3>Outsideri test</h3>")
        self.assertIn("Outsideri test", body)


if __name__ == "__main__":
    unittest.main()
