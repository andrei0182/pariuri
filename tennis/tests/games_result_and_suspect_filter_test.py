"""Teste pentru doua adaugiri din 2026-09-23:
- rezultatul pariului "Peste X game-uri" pe jucatorul recomandat
  (parse_set_scores + check_results.resolve_games), dupa Baez vs Brooksby:
  Baez peste 10.5 game-uri @ 1.52, a pierdut 5-7 5-7 -> 10 game-uri
- plafonul pe edge/estimare (MAX_EDGE_PP / MAX_COMPOSITE_PCT) din
  send_report_email.py, dupa Insfran vs Santos (edge 88.6pp, estimare 97%),
  si regulile de selectie din 2026-10-11

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


def _report_row(p1: str, p2: str, comp1: float, impl1: float, odds1: float, odds2: float,
                tour: str = "atp", elo1: float | None = None, elo_n: int = 20) -> dict:
    return {
        sre._COL_P1: p1, sre._COL_P2: p2, sre._COL_TOUR: tour,
        sre._COL_COMP1: comp1, sre._COL_COMP2: 100 - comp1,
        sre._COL_IMPL1: impl1, sre._COL_IMPL2: 100 - impl1,
        sre._COL_ODDS1: odds1, sre._COL_ODDS2: odds2,
        sre._COL_RATING_CONF: 1.0,
        sre._COL_GAMES_LINE_P1: 3.5, sre._COL_GAMES_ODDS_P1: 1.4,
        sre._COL_GAMES_LINE_P2: 3.5, sre._COL_GAMES_ODDS_P2: 1.4,
        sre._COL_ELO1: comp1 if elo1 is None else elo1, sre._COL_ELO_MIN_N: elo_n,
    }


class PickFilterTests(unittest.TestCase):
    """Regulile v3 (2026-10-11): estimare combinata = piata + 30% din Elo,
    favorit (>= 50%), ambii cu >= 10 meciuri in istoric, cota <= 2.0, fara
    ITF/UTR. Modelul compus vechi doar marcheaza meciurile suspecte."""

    def setUp(self):
        self.df = pd.DataFrame([
            _report_row("Guisella Insfran", "Sophia Santos", 97.0, 8.4, 11.0, 1.03, elo1=10.0),  # suspect, nu pick
            _report_row("Fav Ales", "Adversar Unu", 55.0, 60.0, 1.6, 2.4, elo1=80.0),   # combinat 66% (+6pp) -> pick
            _report_row("Sebastian Baez", "Jenson Brooksby", 57.4, 41.9, 2.25, 1.62),   # outsider: combinat 46.5% -> nu
            _report_row("Fav Itf", "Adversar Doi", 80.0, 60.0, 1.6, 2.4, tour="itf-m"),  # ITF -> nu
            _report_row("Fav Nou", "Adversar Trei", 80.0, 60.0, 1.6, 2.4, elo_n=5),     # istoric Elo prea scurt -> nu
        ])

    def test_only_established_favourite_outside_itf_is_picked(self):
        picks = sre.filter_recommended_picks(self.df)
        self.assertEqual(list(picks[sre._COL_P1]), ["Fav Ales"])
        self.assertAlmostEqual(picks.iloc[0]["_blend_pct"], 66.0)
        self.assertAlmostEqual(picks.iloc[0]["_blend_edge_pp"], 6.0)
        self.assertAlmostEqual(picks.iloc[0]["_elo_pct"], 80.0)

    def test_player2_side(self):
        df = pd.DataFrame([_report_row("Outsider", "Fav Doi", 50.0, 40.0, 2.5, 1.6, elo1=20.0)])  # Elo J2 80%
        picks = sre.filter_recommended_picks(df)
        self.assertEqual(picks.iloc[0]["_recommended_player"], 2)
        self.assertAlmostEqual(picks.iloc[0]["_blend_pct"], 66.0)

    def test_small_elo_edge_on_favourite_is_not_enough(self):
        # Elo +15pp -> combinat doar +4.5pp, sub pragul de 5pp
        df = pd.DataFrame([_report_row("Fav Mic", "X", 75.0, 60.0, 1.6, 2.4)])
        self.assertTrue(sre.filter_recommended_picks(df).empty)

    def test_odds_above_two_rejected(self):
        df = pd.DataFrame([_report_row("Egal", "X", 80.0, 48.0, 2.05, 1.8)])  # combinat 57.6%, dar cota 2.05
        self.assertTrue(sre.filter_recommended_picks(df).empty)

    def test_without_elo_columns_no_picks(self):
        df = self.df.drop(columns=[sre._COL_ELO1, sre._COL_ELO_MIN_N])
        self.assertTrue(sre.filter_recommended_picks(df).empty)

    def test_suspect_listed_separately(self):
        suspects = sre.list_suspect_picks(self.df)
        self.assertEqual(list(suspects[sre._COL_P1]), ["Guisella Insfran"])

    def test_email_body_shows_suspect_section(self):
        body = sre.build_email_body(self.df, "2026-09-23")
        self.assertIn("Suspecte", body)
        self.assertIn("EXPERIMENTAL", body)
        self.assertIn("NU pariați", body)
        self.assertIn("Pick experimental: Fav Ales", body)
        self.assertIn("Elo 80.0%", body)
        self.assertIn("Guisella Insfran", body)


class AddEloColumnsTests(unittest.TestCase):
    def test_probability_and_min_matches_from_book(self):
        import elo
        book = elo.EloBook()
        for _ in range(12):
            book.update("/player/a/", "/player/b/", "Hard")
        df = pd.DataFrame([
            {sre._COL_SLUG1: "/player/a/", sre._COL_SLUG2: "/player/b/", sre._COL_SURFACE: "hard"},
            {sre._COL_SLUG1: "/player/b/", sre._COL_SLUG2: "/player/nou/", sre._COL_SURFACE: ""},
            {sre._COL_SLUG1: float("nan"), sre._COL_SLUG2: "/player/b/", sre._COL_SURFACE: "Clay"},
        ])
        out = sre.add_elo_columns(df, book=book)
        self.assertGreater(out.loc[0, sre._COL_ELO1], 80)
        self.assertEqual(out.loc[0, sre._COL_ELO_MIN_N], 12)
        self.assertEqual(out.loc[1, sre._COL_ELO_MIN_N], 0)
        self.assertTrue(pd.isna(out.loc[2, sre._COL_ELO1]))


if __name__ == "__main__":
    unittest.main()
