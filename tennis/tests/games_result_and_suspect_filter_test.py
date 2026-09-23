"""Teste pentru doua adaugiri din 2026-09-23:
- rezultatul pariului "Peste X game-uri" pe jucatorul recomandat
  (parse_set_scores + check_results.resolve_games), dupa Baez vs Brooksby:
  Baez peste 10.5 game-uri @ 1.52, a pierdut 5-7 5-7 -> 10 game-uri
- plafonul pe edge/estimare (MAX_EDGE_PP / MAX_COMPOSITE_PCT) din
  send_report_email.py, dupa Insfran vs Santos (edge 88.6pp, estimare 97%)

HTML-ul din teste e construit dupa structura PRESUPUSA a td.gScore (vezi
docstring-ul parse_set_scores) - nu e o captura reala a paginii.
Ruleaza fara retea: cd tennis && python -m unittest tests.games_result_and_suspect_filter_test"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import check_results  # noqa: E402
import send_report_email as sre  # noqa: E402
from tenis_scraper.tennisexplorer import MatchDetailData, PlayerProfile, parse_set_scores  # noqa: E402


def _soup(score_html: str) -> BeautifulSoup:
    return BeautifulSoup(f"<table class='gDetail'><tr><td class='gScore'>{score_html}</td></tr></table>", "lxml")


class ParseSetScoresTests(unittest.TestCase):
    def test_straight_sets(self):
        self.assertEqual(parse_set_scores(_soup("0 : 2<br><span>(5-7, 5-7)</span>")), ([(5, 7), (5, 7)], False))

    def test_tiebreak_in_sup_is_not_merged_into_games(self):
        sets, _ = parse_set_scores(_soup("2 : 1<br><span>(7-6<sup>4</sup>, 3-6, 6-2)</span>"))
        self.assertEqual(sets, [(7, 6), (3, 6), (6, 2)])

    def test_retirement_flagged(self):
        self.assertEqual(parse_set_scores(_soup("1 : 0 ret.<br><span>(6-4, 2-1)</span>")), ([(6, 4), (2, 1)], True))

    def test_retirement_inferred_from_unfinished_set(self):
        # Bains vs Jimenez Kasintseva, 2026-09-22: "1:0 (5-2)", fara "ret." in text.
        self.assertEqual(parse_set_scores(_soup("1 : 0<br><span>(5-2)</span>")), ([(5, 2)], True))

    def test_retirement_inferred_from_single_finished_set(self):
        # Tenti vs Kestelboim, 2026-09-21: "1:0 (7-6)".
        self.assertEqual(parse_set_scores(_soup("1 : 0<br><span>(7-6<sup>5</sup>)</span>")), ([(7, 6)], True))

    def test_completed_three_setter_not_retired(self):
        self.assertFalse(parse_set_scores(_soup("2 : 1<br><span>(7-5, 1-6, 5-7)</span>"))[1])

    def test_missing_cell_returns_empty(self):
        self.assertEqual(parse_set_scores(BeautifulSoup("<div></div>", "lxml")), ([], False))


def _detail(p1: str, p2: str, sets: list[tuple[int, int]], retired: bool = False) -> MatchDetailData:
    return MatchDetailData(
        player1=PlayerProfile(name=p1), player2=PlayerProfile(name=p2), set_scores=sets, retired=retired,
    )


def _pick(recommended: str, opponent: str, line: str) -> pd.Series:
    return pd.Series({"recommended_player": recommended, "opponent": opponent, "games_line": line})


class ResolveGamesTests(unittest.TestCase):
    def test_baez_under_line_by_half_game(self):
        detail = _detail("Baez Sebastian", "Brooksby Jenson", [(5, 7), (5, 7)])
        self.assertEqual(
            check_results.resolve_games(_pick("Sebastian Baez", "Jenson Brooksby", "10.5"), detail),
            ("lost", "10", "5-7 5-7"),
        )

    def test_recommended_player_on_right_side_of_page(self):
        # Scorul pe pagina e in ordinea player1-player2; jucatorul recomandat e player2.
        detail = _detail("Brooksby Jenson", "Baez Sebastian", [(7, 5), (6, 7), (6, 4)])
        self.assertEqual(
            check_results.resolve_games(_pick("Sebastian Baez", "Jenson Brooksby", "10.5"), detail),
            ("won", "16", "5-7 7-6 4-6"),
        )

    def test_retirement_is_void(self):
        detail = _detail("Baez Sebastian", "Brooksby Jenson", [(6, 4), (2, 1)], retired=True)
        self.assertEqual(check_results.resolve_games(_pick("Sebastian Baez", "x", "6.5"), detail)[0], "void")

    def test_no_set_scores_leaves_empty(self):
        detail = _detail("Baez Sebastian", "Brooksby Jenson", [])
        self.assertEqual(check_results.resolve_games(_pick("Sebastian Baez", "x", "10.5"), detail), ("", "", ""))


def _report_row(p1: str, p2: str, comp1: float, impl1: float, odds1: float, odds2: float) -> dict:
    return {
        sre._COL_P1: p1, sre._COL_P2: p2,
        sre._COL_COMP1: comp1, sre._COL_COMP2: 100 - comp1,
        sre._COL_IMPL1: impl1, sre._COL_IMPL2: 100 - impl1,
        sre._COL_ODDS1: odds1, sre._COL_ODDS2: odds2,
        sre._COL_RATING_CONF: 1.0,
        sre._COL_GAMES_LINE_P1: 3.5, sre._COL_GAMES_ODDS_P1: 1.4,
        sre._COL_GAMES_LINE_P2: 3.5, sre._COL_GAMES_ODDS_P2: 1.4,
    }


class SuspectEdgeFilterTests(unittest.TestCase):
    def setUp(self):
        self.df = pd.DataFrame([
            _report_row("Guisella Insfran", "Sophia Santos", 97.0, 8.4, 11.0, 1.03),   # edge 88.6 -> suspect
            _report_row("Sebastian Gima", "Filip Misolic", 60.2, 17.2, 5.25, 1.15),   # edge 43.0 -> real, ramane
            _report_row("Sebastian Baez", "Jenson Brooksby", 57.4, 41.9, 2.25, 1.62),  # edge 15.5 -> ramane
        ])

    def test_suspect_excluded_from_picks(self):
        picks = sre.filter_recommended_picks(self.df)
        self.assertEqual(sorted(picks[sre._COL_P1]), ["Sebastian Baez", "Sebastian Gima"])

    def test_suspect_listed_separately(self):
        suspects = sre.list_suspect_picks(self.df)
        self.assertEqual(list(suspects[sre._COL_P1]), ["Guisella Insfran"])

    def test_email_body_shows_suspect_section(self):
        body = sre.build_email_body(self.df, "2026-09-23")
        self.assertIn("Suspecte", body)
        self.assertIn("EXPERIMENTAL", body)
        self.assertIn("NU pariați", body)
        self.assertNotIn("Recomandare:", body)
        self.assertIn("Guisella Insfran", body)


if __name__ == "__main__":
    unittest.main()
