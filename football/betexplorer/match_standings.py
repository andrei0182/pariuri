from __future__ import annotations

import logging
import re

import requests

logger = logging.getLogger(__name__)

# ---- Confirmed (2026-09-13), via curl (NOT Selenium — see note below) -------
# Per-team Over/Under hit-rate stats live on a LEAGUE/SEASON standings AJAX
# endpoint:
#   {league_base_url}standings/?table=over_under&table_sub=overall&ts={ts}
#       &dcheck=0&as-ajax=1&l=en
# where league_base_url is the match URL with its last two path segments
# (match-slug/match-id/) stripped, e.g.
#   https://www.betexplorer.com/football/england/premier-league/
# The `ts` session token is server-rendered directly in that league page's
# raw HTML (in the Standings section's tab links) — a plain GET with a
# browser-like User-Agent returns it instantly, confirmed via curl.
#
# CRITICAL: don't fetch this via Selenium/Chrome. Extensive testing
# (2026-09-13) across ~10 different matches, multiple leagues (including
# Premier League), headless and non-headless Chrome, and three different
# in-page interaction strategies (raw page_source polling, DOM element
# waiting, and clicking the real "Over/Under" tab) ALL failed consistently
# — the token/widget did not appear within 60-90s in Chrome even though the
# exact same content is available instantly via a plain HTTP GET (confirmed
# via curl from the same machine/network in under a second). The bottleneck
# is specific to the Selenium/Chrome pipeline in this environment (likely
# anti-automation handling or simply how that particular async widget
# renders in a scripted browser), not the site's data or this ts/endpoint
# approach — don't waste time re-adding a Selenium-based path here.
#
# The response HTML contains one <div id="box-table-type-6-{line}"> per O/U
# line (0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5), each with a full league table:
# every team's name, matches played, Over count, Under count. Since this is
# a league-wide table (not per-match), fetch once per league and cache —
# every match in that league during this run reuses the same fetch.
_TS_PATTERN = re.compile(r"[?&]ts=([A-Za-z0-9]+)")
_TEAM_ROW_PATTERN = re.compile(
    r"getUrlByWinType\('/football/team/[^/]+/[A-Za-z0-9]+/'\);\">([^<]+)</a>.*?"
    r'<td class="matches_played col_matches_played">(\d+)</td>\s*'
    r'<td class="over col_over">(\d+)</td>\s*'
    r'<td class="under col_under">(\d+)</td>',
    re.DOTALL,
)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_session = requests.Session()
_session.headers.update({"User-Agent": _USER_AGENT, "X-Requested-With": "XMLHttpRequest"})

# league_base_url -> {team_name_lower: {line: (matches_played, over, under)}}, or None on failure
_league_cache: dict[str, dict[str, dict[float, tuple[int, int, int]]] | None] = {}


def build_league_base_url(match_url: str) -> str:
    """Strip the match-slug/match-id/ tail off a confirmed match URL to get
    the league/season base URL, e.g.
    "https://www.betexplorer.com/football/england/premier-league/lille-troyes/EVVF4G0T/"
    -> "https://www.betexplorer.com/football/england/premier-league/"
    """
    trimmed = match_url.rstrip("/")
    base, _match_slug, _match_id = trimmed.rsplit("/", 2)
    return base + "/"


def discover_ts_token(league_base_url: str, timeout: float = 10.0) -> str | None:
    """Plain GET of the league's own page — the `ts` token is right there in
    the server-rendered HTML, no browser/JS execution needed.
    """
    try:
        resp = _session.get(league_base_url, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("discover_ts_token: request failed for %s: %s", league_base_url, exc)
        return None
    match = _TS_PATTERN.search(resp.text)
    return match.group(1) if match else None


def fetch_league_over_under_html(league_base_url: str, timeout: float = 15.0) -> str | None:
    ts = discover_ts_token(league_base_url, timeout=timeout)
    if not ts:
        return None
    url = f"{league_base_url}standings/?table=over_under&table_sub=overall&ts={ts}&dcheck=0&as-ajax=1&l=en"
    try:
        resp = _session.get(url, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("fetch_league_over_under_html: request failed for %s: %s", url, exc)
        return None
    return resp.text


def parse_all_teams_for_line(html: str, line: float) -> dict[str, tuple[int, int, int]]:
    """Returns {team_name_lower: (matches_played, over, under)} for every
    team in one O/U line's box within the full league response.
    """
    line_key = f"{line:g}"
    if "." not in line_key:
        line_key = f"{line:.1f}"
    box_start = html.find(f'id="box-table-type-6-{line_key}"')
    if box_start == -1:
        return {}
    box_end = html.find(f'id="last_updated_box-table-type-6-{line_key}"', box_start)
    box_html = html[box_start : box_end if box_end != -1 else None]

    result: dict[str, tuple[int, int, int]] = {}
    for match in _TEAM_ROW_PATTERN.finditer(box_html):
        team_name, matches_played, over, under = match.groups()
        result[team_name.strip().lower()] = (int(matches_played), int(over), int(under))
    return result


def get_league_stats(
    match_url: str, lines: tuple[float, ...] = (1.5, 2.5, 3.5)
) -> dict[str, dict[float, tuple[int, int, int]]] | None:
    """Fetch (once per league, cached for the rest of this run) every team's
    hit-rate stats for the given O/U lines. Returns None if the league's
    standings couldn't be fetched at all (e.g. genuinely no standings for
    this competition, or a request failure) — failures are cached too, so a
    broken league is only retried once per run, not once per match.
    """
    league_base_url = build_league_base_url(match_url)
    if league_base_url in _league_cache:
        return _league_cache[league_base_url]

    html = fetch_league_over_under_html(league_base_url)
    if not html:
        _league_cache[league_base_url] = None
        return None

    teams: dict[str, dict[float, tuple[int, int, int]]] = {}
    for line in lines:
        for team_name_lower, stats in parse_all_teams_for_line(html, line).items():
            teams.setdefault(team_name_lower, {})[line] = stats

    _league_cache[league_base_url] = teams
    return teams


def extract_over_under_stats(
    match_url: str,
    home_team: str,
    away_team: str,
    lines: tuple[float, ...] = (1.5, 2.5, 3.5),
) -> tuple["TeamOverUnderStats", "TeamOverUnderStats"] | None:
    """Look up both teams' hit-rate stats for the given O/U lines, from the
    (cached) league-wide table. Returns None if the league's stats couldn't
    be fetched at all, or neither team was found in them (e.g. a genuine
    name mismatch, or a cup competition with no standings table).
    """
    from .models import TeamOverUnderStats  # local import to avoid a cycle at module load

    league_stats = get_league_stats(match_url, lines=lines)
    if league_stats is None:
        return None

    home_data = league_stats.get(home_team.strip().lower())
    away_data = league_stats.get(away_team.strip().lower())
    if not home_data and not away_data:
        return None

    home_stats = TeamOverUnderStats()
    away_stats = TeamOverUnderStats()
    found_any = False
    for line in lines:
        line_key = f"{line:.1f}".replace(".", "_")
        if home_data and line in home_data:
            _matches, over, under = home_data[line]
            setattr(home_stats, f"over_{line_key}", str(over))
            setattr(home_stats, f"under_{line_key}", str(under))
            found_any = True
        if away_data and line in away_data:
            _matches, over, under = away_data[line]
            setattr(away_stats, f"over_{line_key}", str(over))
            setattr(away_stats, f"under_{line_key}", str(under))
            found_any = True

    return (home_stats, away_stats) if found_any else None
