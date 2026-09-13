from __future__ import annotations

import logging

from .match_odds import extract_match_id, fetch_over_under_odds
from .match_standings import extract_over_under_stats as _extract_hit_rate_stats
from .models import OddsOverUnder, TeamOverUnderStats

logger = logging.getLogger(__name__)


def scrape_match_stats(
    match_url: str, home_team: str, away_team: str
) -> tuple[bool, TeamOverUnderStats | None, TeamOverUnderStats | None, OddsOverUnder]:
    """Full per-match pipeline: odds + hit-rate stats. Returns
    (stats_eligible, home_stats, away_stats, odds_ou).

    CONFIRMED (2026-09-13): neither odds nor hit-rate stats need a browser
    page load at all anymore — both go through plain HTTP requests
    (match_odds.py / match_standings.py). No Selenium WebDriver is needed
    for this function; it no longer takes a `driver` argument. Selenium is
    only needed once per run now, for the initial daily match-list page
    (see match_list.py) — everything downstream of that is plain HTTP.

    stats_eligible reflects whether hit-rate stats were actually found for
    either team, consistent with the client's own definition of an eligible
    match (cup matches, single-leg ties, and friendlies have no standings
    table — see the spec PDF's "Management of non-league matches" section).
    """
    match_id = extract_match_id(match_url)
    odds_ou = fetch_over_under_odds(match_id, line=2.5) if match_id else OddsOverUnder(line=2.5)

    result = _extract_hit_rate_stats(match_url, home_team, away_team)
    if result is None:
        return False, TeamOverUnderStats(), TeamOverUnderStats(), odds_ou

    home_stats, away_stats = result
    return True, home_stats, away_stats, odds_ou
