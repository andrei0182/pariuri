from __future__ import annotations

import logging

from .match_odds import extract_match_id, fetch_1x2_odds, fetch_over_under_odds
from .match_standings import extract_over_under_stats as _extract_hit_rate_stats
from .models import Odds1X2, OddsOverUnder, TeamOverUnderStats

logger = logging.getLogger(__name__)


def scrape_match_stats(
    match_url: str, home_team: str, away_team: str
) -> tuple[bool, TeamOverUnderStats | None, TeamOverUnderStats | None, OddsOverUnder, Odds1X2]:
    """Full per-match pipeline: odds + hit-rate stats. Returns
    (stats_eligible, home_stats, away_stats, odds_ou, odds_1x2).

    CONFIRMED (2026-09-13/14): none of odds_ou, odds_1x2, or hit-rate stats
    need a browser page load anymore — all go through plain HTTP requests
    (match_odds.py / match_standings.py). No Selenium WebDriver is needed
    for this function; it no longer takes a `driver` argument. Selenium is
    only needed once per run now, for the initial daily match-list page
    (see match_list.py) — everything downstream of that is plain HTTP.

    odds_1x2 here is fetched via AJAX (see match_odds.fetch_1x2_odds) and
    should be treated as authoritative — the list-page DOM scrape's own
    odds_1x2 attempt (match_list.py) was found unreliable (0% coverage
    across an entire fresh run) and callers should prefer this value when
    --with-stats is used.

    stats_eligible reflects whether hit-rate stats were actually found for
    either team, consistent with the client's own definition of an eligible
    match (cup matches, single-leg ties, and friendlies have no standings
    table — see the spec PDF's "Management of non-league matches" section).
    """
    match_id = extract_match_id(match_url)
    odds_ou = fetch_over_under_odds(match_id, line=2.5) if match_id else OddsOverUnder(line=2.5)
    odds_1x2 = fetch_1x2_odds(match_id) if match_id else Odds1X2()

    result = _extract_hit_rate_stats(match_url, home_team, away_team)
    if result is None:
        return False, TeamOverUnderStats(), TeamOverUnderStats(), odds_ou, odds_1x2

    home_stats, away_stats = result
    return True, home_stats, away_stats, odds_ou, odds_1x2
