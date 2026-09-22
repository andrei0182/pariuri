"""Teste pentru ajustarea de oboseala (_parse_recent_match_date,
_matches_played_within, _fatigue_penalty_pp din main.py), adaugata
2026-09-22 dupa recomandarea gresita pe Santiago Rodriguez Taverna vs
Pedro Boscardin Dias (Taverna, epuizat dupa 3 meciuri in 3 zile, a fost
recomandat cu 58.2% sanse si a pierdut categoric).

Numele fisierului NU incepe cu "test_" intentionat - acel prefix e
exclus explicit in .gitignore (rezervat scratch-urilor de sesiune).
Ruleaza fara retea: cd tennis && python -m unittest tests.fatigue_adjustment_test"""
from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402
from tenis_scraper.tennisexplorer import RecentMatch  # noqa: E402


class ParseRecentMatchDateTests(unittest.TestCase):
    def test_reads_date_field_when_present(self):
        m = RecentMatch(tournament="X", round="1R", date="21.09.2026", opponent="o", score="2:0")
        self.assertEqual(main._parse_recent_match_date(m), dt.date(2026, 9, 21))

    def test_falls_back_to_round_field_for_team_league_matches(self):
        # Bundesliga/Swiss Nationalliga: data ajunge in `round`, `date` ramane gol.
        m = RecentMatch(tournament="Bundesliga - men", round="09.08.2026", date="", opponent="o", score="2:0")
        self.assertEqual(main._parse_recent_match_date(m), dt.date(2026, 8, 9))

    def test_returns_none_when_neither_field_parses(self):
        m = RecentMatch(tournament="X", round="1R", date="", opponent="o", score="2:0")
        self.assertIsNone(main._parse_recent_match_date(m))


class MatchesPlayedWithinTests(unittest.TestCase):
    def test_counts_only_matches_inside_3_day_window(self):
        reference = dt.date(2026, 9, 22)
        recent = [
            RecentMatch(tournament="A", round="1R", date="22.09.2026", opponent="o", score="2:0"),
            RecentMatch(tournament="A", round="Q-R16", date="21.09.2026", opponent="o", score="2:0"),
            RecentMatch(tournament="A", round="Q-1R", date="20.09.2026", opponent="o", score="2:1"),
            RecentMatch(tournament="A", round="R16", date="19.09.2026", opponent="o", score="2:0"),  # in afara ferestrei
        ]
        self.assertEqual(main._matches_played_within(recent, reference), 3)

    def test_zero_when_no_recent_matches(self):
        reference = dt.date(2026, 9, 22)
        recent = [RecentMatch(tournament="A", round="1R", date="04.08.2026", opponent="o", score="2:0")]
        self.assertEqual(main._matches_played_within(recent, reference), 0)


class FatiguePenaltyPpTests(unittest.TestCase):
    def test_penalty_table_tiers(self):
        self.assertEqual(main._fatigue_penalty_pp(0), 0.0)
        self.assertEqual(main._fatigue_penalty_pp(1), 3.0)
        self.assertEqual(main._fatigue_penalty_pp(2), 6.0)
        self.assertEqual(main._fatigue_penalty_pp(3), 10.0)
        self.assertEqual(main._fatigue_penalty_pp(5), 10.0)


class TavernaBoscardinRegressionTest(unittest.TestCase):
    """Reface starea reala de dinainte de meci (2026-09-22): Taverna jucase
    2 calificari in ziua precedenta, Boscardin nu jucase nimic recent -
    ajustarea trebuie sa scada estimarea sub pragul de 55% folosit in
    productie de send_report_email.py (MIN_COMPOSITE_PCT), care ar fi
    exclus aceasta recomandare din raport."""

    def test_fatigue_adjustment_drops_estimate_below_production_threshold(self):
        match_date = dt.date(2026, 9, 22)
        p1_recent = [
            RecentMatch(tournament="Buenos Aires challenger", round="Q-R16", date="21.09.2026", opponent="o", score="2:0"),
            RecentMatch(tournament="Buenos Aires challenger", round="Q-1R", date="21.09.2026", opponent="o", score="2:1"),
            RecentMatch(tournament="Szczecin challenger", round="Q-R16", date="14.09.2026", opponent="o", score="2:0"),
        ]
        p2_recent = [
            RecentMatch(tournament="Bundesliga - men", round="09.08.2026", date="", opponent="o", score="2:0"),
        ]

        n1 = main._matches_played_within(p1_recent, match_date)
        n2 = main._matches_played_within(p2_recent, match_date)
        self.assertEqual(n1, 2)
        self.assertEqual(n2, 0)

        composite_p1_before = 0.582  # ce a aratat raportul de dimineata (2026-09-22)
        adj_pp = main._fatigue_penalty_pp(n2) - main._fatigue_penalty_pp(n1)
        composite_p1_after = min(max(composite_p1_before + adj_pp / 100, 0.0), 1.0)

        self.assertEqual(adj_pp, -6.0)
        self.assertAlmostEqual(composite_p1_after, 0.522, places=3)
        MIN_COMPOSITE_PCT_PRODUCTIE = 0.55  # send_report_email.py MIN_COMPOSITE_PCT
        self.assertLess(composite_p1_after, MIN_COMPOSITE_PCT_PRODUCTIE)


if __name__ == "__main__":
    unittest.main()
