"""Teste pentru semnalele pe jucatori adaugate 2026-09-23: suprafata
meciului, H2H real si forma ponderata dupa recenta. Parserele sunt testate
pe HTML REAL de pe TennisExplorer (tests/fixtures/, descarcat din CI), nu
pe HTML construit de mana.
Ruleaza fara retea: cd tennis && python -m unittest tests.player_signals_test"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402
from tenis_scraper import tennisexplorer as te  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _detail(name: str) -> te.MatchDetailData:
    return te.parse_match_detail((FIXTURES / f"{name}.html").read_text(encoding="utf-8"))


class RealPageParsingTests(unittest.TestCase):
    def test_surface_from_header(self):
        self.assertEqual(_detail("match_baez_brooksby").surface, "Hard")
        self.assertEqual(_detail("match_arifullina_ruchkina").surface, "Hard")

    def test_h2h_table(self):
        d = _detail("match_baez_brooksby")
        self.assertTrue(d.h2h_exists)
        self.assertEqual(
            [(m.year, m.tournament, m.surface, m.winner, m.sets, m.match_id) for m in d.h2h_matches],
            [
                (2026, "Chengdu", "Hard", "Brooksby", [(7, 5), (7, 5)], 3329361),
                (2026, "Rome", "Clay", "Baez", [(6, 3), (7, 6)], None),
                (2026, "Auckland", "Hard", "Baez", [(7, 5), (6, 0)], None),
            ],
        )

    def test_no_h2h(self):
        d = _detail("match_arifullina_ruchkina")
        self.assertFalse(d.h2h_exists)
        self.assertEqual(d.h2h_matches, [])

    def test_set_scores_on_real_page(self):
        d = _detail("match_baez_brooksby")
        self.assertEqual((d.set_scores, d.retired), ([(7, 5), (7, 5)], False))


class H2HSignalTests(unittest.TestCase):
    def setUp(self):
        self.detail = _detail("match_baez_brooksby")  # player1 pe pagina = Brooksby

    def test_current_match_excluded_and_baez_favoured(self):
        p_brooksby, weight = main._h2h_probability(
            self.detail.h2h_matches, self.detail.player1.name, "Hard", 2026, exclude_match_id=3329361,
        )
        # Baez 2-0 inainte de Chengdu (1.5 pe hard + 1.0 pe zgura) -> Brooksby (0+1)/(2.5+2)
        self.assertAlmostEqual(p_brooksby, 1 / 4.5)
        self.assertAlmostEqual(weight, main.H2H_MAX_WEIGHT * 2.5 / 4)

    def test_current_match_without_link_is_excluded(self):
        # Ivanov vs Lemaitre: singurul rand H2H e meciul insusi, fara link match-detail
        d = _detail("match_ivanov_lemaitre")
        self.assertEqual([(m.winner, m.match_id, m.is_current) for m in d.h2h_matches], [("Lemaitre", None, True)])
        self.assertEqual(main._h2h_probability(d.h2h_matches, d.player1.name, "Hard", 2026), (None, 0.0))

    def test_no_meetings_gives_no_signal(self):
        self.assertEqual(main._h2h_probability([], "Baez Sebastian", "Hard", 2026), (None, 0.0))

    def test_older_meetings_count_less(self):
        old = te.H2HMatch(year=2022, surface="Clay", winner="Baez", loser="Brooksby")
        p, _ = main._h2h_probability([old], "Baez Sebastian", "Hard", 2026)
        self.assertAlmostEqual(p, (0.8 ** 4 + 1) / (0.8 ** 4 + 2))


class SurfaceSignalTests(unittest.TestCase):
    def test_uses_match_surface_not_all_surfaces(self):
        balance = {"Clay": ("20/2", "2/20"), "Hard": ("5/5", "5/5")}
        on_hard, _ = main._surface_rating_probability(balance, "Hard")
        on_clay, _ = main._surface_rating_probability(balance, "Clay")
        self.assertLess(abs(on_hard - 0.5), abs(on_clay - 0.5))
        self.assertGreater(on_clay, 0.9)

    def test_unknown_surface_falls_back_to_career(self):
        balance = {"Clay": ("9/6", "6/6")}
        self.assertEqual(
            main._surface_rating_probability(balance, ""), main._career_rating_probability(balance),
        )


class WeightedFormTests(unittest.TestCase):
    def test_recent_results_weigh_more(self):
        won, lost = te.RecentMatch(won=True), te.RecentMatch(won=False)
        recent_wins = main._form_probability(*main._weighted_form([won, won, lost, lost]),
                                             *main._weighted_form([lost, lost, won, won]))
        self.assertGreater(recent_wins, 0.5)


if __name__ == "__main__":
    unittest.main()
