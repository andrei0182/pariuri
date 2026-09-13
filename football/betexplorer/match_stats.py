from __future__ import annotations

import logging

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from . import selectors as sel
from .consent import dismiss_overlays
from .match_odds import extract_match_id, fetch_over_under_odds
from .match_standings import extract_over_under_stats as _extract_hit_rate_stats
from .models import OddsOverUnder, TeamOverUnderStats

logger = logging.getLogger(__name__)

DEFAULT_WAIT = 15


def is_stats_eligible(driver: WebDriver) -> bool:
    """Step 7: a match only has Over/Under stats if its page has a standings table.

    NOT YET CONFIRMED — STANDINGS_TABLE is still a guessed selector (see
    selectors.py). Deliberately DOM-based rather than a competition-name
    heuristic ('Cup' in the name) once confirmed, since competitions like the
    Champions League have no standings table either despite not being
    literally a 'cup'.
    """
    return len(driver.find_elements(By.CSS_SELECTOR, sel.STANDINGS_TABLE)) > 0


def extract_over_under_stats(
    driver: WebDriver,
    match_url: str,
    match_id: str,
    home_team: str,
    away_team: str,
    wait_seconds: int = DEFAULT_WAIT,
) -> tuple[TeamOverUnderStats, TeamOverUnderStats]:
    """Step 8: per-team Over/Under hit-rate stats (e.g. "24 of 38 games went
    Over 2.5"), via the confirmed league-standings AJAX endpoint
    (match_standings.py) — reads the 1.5/2.5/3.5 lines for both teams in one
    fetch. Returns empty TeamOverUnderStats() for both sides if any part of
    the lookup (ts token, either team's id, or the fetch itself) fails,
    rather than raising — the caller (scrape_match_stats) already treats a
    failed lookup the same as any other per-match scrape error.
    """
    result = _extract_hit_rate_stats(driver, match_url, match_id, home_team, away_team, wait_seconds=wait_seconds)
    if result is None:
        return TeamOverUnderStats(), TeamOverUnderStats()
    return result


def scrape_match_stats(
    driver: WebDriver, match_url: str, home_team: str, away_team: str, wait_seconds: int = DEFAULT_WAIT
) -> tuple[bool, TeamOverUnderStats | None, TeamOverUnderStats | None, OddsOverUnder]:
    """Full per-match pipeline for one match page. Returns (stats_eligible,
    home_stats, away_stats, odds_ou).

    odds_ou and the hit-rate stats are both fetched via confirmed AJAX
    endpoints and don't depend on stats_eligible — stats_eligible itself is
    still based on the unconfirmed STANDINGS_TABLE selector (see
    is_stats_eligible) and is kept only so callers can distinguish "no
    standings table at all for this competition" from "lookup failed"; both
    currently just leave home_stats/away_stats at their default values, so
    this flag doesn't gate anything yet.
    """
    driver.get(match_url)
    try:
        WebDriverWait(driver, wait_seconds).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except TimeoutException:
        pass
    dismiss_overlays(driver)

    match_id = extract_match_id(match_url)
    odds_ou = fetch_over_under_odds(driver, match_id, line=2.5) if match_id else OddsOverUnder(line=2.5)

    eligible = is_stats_eligible(driver)
    if not match_id:
        return eligible, None, None, odds_ou

    home_stats, away_stats = extract_over_under_stats(
        driver, match_url, match_id, home_team, away_team, wait_seconds
    )
    return eligible, home_stats, away_stats, odds_ou
