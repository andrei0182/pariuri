from __future__ import annotations

import logging

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait

from .consent import dismiss_overlays
from .match_odds import extract_match_id, fetch_over_under_odds
from .match_standings import extract_over_under_stats as _extract_hit_rate_stats
from .models import OddsOverUnder, TeamOverUnderStats

logger = logging.getLogger(__name__)

DEFAULT_WAIT = 15


def scrape_match_stats(
    driver: WebDriver, match_url: str, home_team: str, away_team: str, wait_seconds: int = DEFAULT_WAIT
) -> tuple[bool, TeamOverUnderStats | None, TeamOverUnderStats | None, OddsOverUnder]:
    """Full per-match pipeline for one match page. Returns (stats_eligible,
    home_stats, away_stats, odds_ou).

    odds_ou still goes through the browser session (Selenium execute_async_script)
    since it needs the match page's own cookies/context and doesn't need a ts
    token. Hit-rate stats (home_stats/away_stats) now go through plain HTTP
    requests instead (see match_standings.py) — confirmed far faster and more
    reliable than the Selenium-based approach it replaces; driver is no
    longer needed for that part at all.

    stats_eligible reflects whether hit-rate stats were actually found for
    either team, consistent with the client's own definition of an eligible
    match (cup matches, single-leg ties, and friendlies have no standings
    table — see the spec PDF's "Management of non-league matches" section).
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

    result = _extract_hit_rate_stats(match_url, home_team, away_team)
    if result is None:
        return False, TeamOverUnderStats(), TeamOverUnderStats(), odds_ou

    home_stats, away_stats = result
    return True, home_stats, away_stats, odds_ou
