"""Teste pentru find_scheduled_match() - in special detectia de ordine
inversata (swap) intre player1/player2 Superbet si player1/player2
TennisExplorer, corectata 2026-09-22 (vezi git log tenis_scraper/tennisexplorer.py).
Numele fisierului NU incepe cu "test_" intentionat - acel prefix e
exclus explicit in .gitignore (rezervat scratch-urilor de sesiune), deci
un test_*.py real nu ar ajunge comis. Ruleaza fara retea:
python -m unittest tennis.tests.find_scheduled_match_test
(sau, din directorul tennis/: python -m unittest tests.find_scheduled_match_test)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tenis_scraper.tennisexplorer import ScheduledMatch, find_scheduled_match  # noqa: E402


class FindScheduledMatchTests(unittest.TestCase):
    def test_direct_order_not_flagged_as_swapped(self):
        schedule = [ScheduledMatch(player1="Pennaforti G.", player2="Ionel N.D.", match_id=3328741)]
        result = find_scheduled_match("Gabriele Pennaforti", "Nicholas David Ionel", schedule)
        self.assertIsNotNone(result)
        scheduled, swapped = result
        self.assertEqual(scheduled.match_id, 3328741)
        self.assertFalse(swapped)

    def test_reversed_order_is_flagged_as_swapped(self):
        # Cazul care declansa bug-ul: TennisExplorer lista jucatorii in
        # ordine inversa fata de Superbet - caller-ul TREBUIE sa
        # interschimbe rank/forma/rating cand swapped=True.
        schedule = [ScheduledMatch(player1="Ionel N.D.", player2="Pennaforti G.", match_id=3328741)]
        result = find_scheduled_match("Gabriele Pennaforti", "Nicholas David Ionel", schedule)
        self.assertIsNotNone(result)
        scheduled, swapped = result
        self.assertEqual(scheduled.match_id, 3328741)
        self.assertTrue(swapped)

    def test_no_match_returns_none(self):
        schedule = [ScheduledMatch(player1="Someone A.", player2="Else B.", match_id=1)]
        result = find_scheduled_match("Gabriele Pennaforti", "Nicholas David Ionel", schedule)
        self.assertIsNone(result)

    def test_direct_match_preferred_over_swapped_when_both_present(self):
        # Daca in acelasi schedule exista si o potrivire directa si una
        # inversata (nume ambigue), functia trebuie sa returneze prima
        # potrivire gasita in ordinea listei - aici directa.
        schedule = [
            ScheduledMatch(player1="Pennaforti G.", player2="Ionel N.D.", match_id=111),
            ScheduledMatch(player1="Ionel N.D.", player2="Pennaforti G.", match_id=222),
        ]
        result = find_scheduled_match("Gabriele Pennaforti", "Nicholas David Ionel", schedule)
        self.assertIsNotNone(result)
        scheduled, swapped = result
        self.assertEqual(scheduled.match_id, 111)
        self.assertFalse(swapped)

    def test_matching_is_case_and_diacritic_insensitive_on_surname(self):
        schedule = [ScheduledMatch(player1="pennaforti g.", player2="IONEL N.D.", match_id=999)]
        result = find_scheduled_match("Gabriele Pennaforti", "Nicholas David Ionel", schedule)
        self.assertIsNotNone(result)
        scheduled, swapped = result
        self.assertEqual(scheduled.match_id, 999)
        self.assertFalse(swapped)


if __name__ == "__main__":
    unittest.main()
