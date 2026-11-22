"""Teste pentru extract_table_id / extract_team_ids cand Superbet trimite null
(2026-11-22: 46 din 730 de meciuri pierdeau statisticile cu AttributeError).
Ruleaza: cd football && python -m unittest tests.superbet_stats_test"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from superbet.stats import extract_table_id, extract_team_ids  # noqa: E402


class ExtractIdsTest(unittest.TestCase):
    def test_table_id_null(self):
        self.assertIsNone(extract_table_id({"table_id": None}))

    def test_table_id_missing(self):
        self.assertIsNone(extract_table_id({}))

    def test_table_id_present(self):
        self.assertEqual(extract_table_id({"table_id": {"value": "abc"}}), "abc")

    def test_team_ids_null(self):
        self.assertEqual(extract_team_ids({"team1": None, "team2": {"id": "t2"}}), (None, "t2"))


if __name__ == "__main__":
    unittest.main()
