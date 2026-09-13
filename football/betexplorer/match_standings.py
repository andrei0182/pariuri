from __future__ import annotations

import re

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

# ---- Confirmed (2026-09-12), via DevTools on a real match page --------------
# Per-team Over/Under hit-rate stats (Steps 7-8's original goal) live on a
# LEAGUE/SEASON standings AJAX endpoint, not a per-match one:
#   {league_base_url}standings/?table=over_under&table_sub=overall&ts={ts}
#       &dcheck=0&as-ajax=1&l=en&event_context={match_id}
# where league_base_url is the match URL with its last two path segments
# (match-slug/match-id/) stripped, e.g.
#   https://www.betexplorer.com/football/england/premier-league-2025-2026/
# CONFIRMED DIFFERENCES from the OU-odds endpoint (match_odds.py):
#   - needs a `ts` session token (the OU-odds endpoint didn't)
#   - returns raw HTML directly, NOT a {"odds": "..."} JSON wrapper
# The response contains one <div id="box-table-type-6-{line}"> per O/U line
# (0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5), each with a full 20-team league table:
# matches played, Over count, Under count, goals for:against, goals/match,
# and last-5-matches form. Rows are tagged data-def-order and a class
# "glib-participant-{team_id}" — team_id matches the id in that team's
# profile URL (/football/team/{slug}/{team_id}/).
_TS_PATTERN = re.compile(r"[?&]ts=([A-Za-z0-9]+)")
_TEAM_ROW_PATTERN = re.compile(
    r'glib-participant-([A-Za-z0-9]+)".*?'
    r'<td class="matches_played col_matches_played">(\d+)</td>\s*'
    r'<td class="over col_over">(\d+)</td>\s*'
    r'<td class="under col_under">(\d+)</td>',
    re.DOTALL,
)


def build_league_base_url(match_url: str) -> str:
    """Strip the match-slug/match-id/ tail off a confirmed match URL to get
    the league/season base URL, e.g.
    "https://www.betexplorer.com/football/england/premier-league-2025-2026/sunderland-arsenal/YoNI2r8F/"
    -> "https://www.betexplorer.com/football/england/premier-league-2025-2026/"
    """
    trimmed = match_url.rstrip("/")
    base, _match_slug, _match_id = trimmed.rsplit("/", 2)
    return base + "/"


def discover_ts_token(driver: WebDriver) -> str | None:
    """Find the `ts` session token by regex-searching the currently loaded
    page's source. CONFIRMED to appear in ts=XXXXXXXX form somewhere in the
    match page's own AJAX links (it's the same token the page's own JS uses
    to call this same standings endpoint when a person clicks the O/U tab).
    """
    match = _TS_PATTERN.search(driver.page_source)
    return match.group(1) if match else None


def build_standings_url(
    match_url: str, ts: str, match_id: str, table_sub: str = "overall"
) -> str:
    base = build_league_base_url(match_url)
    return (
        f"{base}standings/?table=over_under&table_sub={table_sub}&ts={ts}"
        f"&dcheck=0&as-ajax=1&l=en&event_context={match_id}"
    )


def fetch_standings_html(
    driver: WebDriver, url: str, wait_seconds: float = 15.0
) -> str | None:
    """Fetch the standings AJAX endpoint's raw HTML response. Returns None on
    any failure (network, missing ts, etc.) rather than raising — caller
    decides how to handle a miss.
    """
    script = """
    var callback = arguments[arguments.length - 1];
    fetch(arguments[0], {headers: {'X-Requested-With': 'XMLHttpRequest'}, credentials: 'same-origin'})
        .then(function(r) { return r.text(); })
        .then(function(data) { callback(data); })
        .catch(function(err) { callback(null); });
    """
    try:
        driver.set_script_timeout(wait_seconds)
        return driver.execute_async_script(script, url)
    except Exception:
        return None


def parse_team_over_under_row(
    html: str, team_id: str, line: float = 2.5
) -> tuple[int, int, int] | None:
    """Find one team's row within the box for the given O/U line.

    Returns (matches_played, over_count, under_count), or None if the line's
    box or the team's row isn't found in the response.
    """
    line_key = f"{line:g}"  # 2.5 -> "2.5", 1.0 -> "1" — matches the site's box-id format for whole numbers seen (e.g. table=2 not confirmed; only .5 lines seen so far)
    if "." not in line_key:
        line_key = f"{line:.1f}"
    box_start = html.find(f'id="box-table-type-6-{line_key}"')
    if box_start == -1:
        return None
    box_end = html.find(f'id="last_updated_box-table-type-6-{line_key}"', box_start)
    box_html = html[box_start : box_end if box_end != -1 else None]

    for match in _TEAM_ROW_PATTERN.finditer(box_html):
        row_team_id, matches_played, over, under = match.groups()
        if row_team_id == team_id:
            return int(matches_played), int(over), int(under)
    return None


_TEAM_PROFILE_URL_PATTERN = re.compile(r"/football/team/[^/]+/([A-Za-z0-9]+)/?$")


def extract_team_id(driver: WebDriver, team_name: str) -> str | None:
    """Find a team's id by matching an anchor's visible text against
    team_name (case-insensitive), among links to team profile pages.

    CONFIRMED (2026-09-12): on a match's own page, exactly two anchors with
    href*='/football/team/' carry visible text — the home and away team
    names — and both link straight to that team's profile URL
    (/football/team/{slug}/{team_id}/). The rest of the team-profile links
    on the page (from an embedded standings/form widget covering the whole
    league) have empty visible text, so matching on non-empty text that
    equals the team's name (as already known from the daily match list) is
    reliable — no need to touch the standings AJAX response at all for this
    lookup.
    """
    needle = team_name.strip().lower()
    links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/football/team/']")
    for link in links:
        text = (link.text or "").strip().lower()
        if text != needle:
            continue
        href = link.get_attribute("href") or ""
        match = _TEAM_PROFILE_URL_PATTERN.search(href)
        if match:
            return match.group(1)
    return None


def extract_over_under_stats(
    driver: WebDriver,
    match_url: str,
    match_id: str,
    home_team: str,
    away_team: str,
    lines: tuple[float, ...] = (1.5, 2.5, 3.5),
    wait_seconds: float = 15.0,
) -> tuple["TeamOverUnderStats", "TeamOverUnderStats"] | None:
    """Full pipeline: discover the ts token, resolve both teams' ids, fetch
    the standings response once, and read off each requested O/U line for
    both teams.

    Returns None (rather than raising) if the ts token, either team's id, or
    the standings fetch itself can't be resolved — callers should treat that
    as "stats unavailable for this match" and move on, the same as
    stats_eligible=False elsewhere in this pipeline.
    """
    from .models import TeamOverUnderStats  # local import to avoid a cycle at module load

    ts = discover_ts_token(driver)
    if not ts:
        return None

    home_id = extract_team_id(driver, home_team)
    away_id = extract_team_id(driver, away_team)
    if not home_id or not away_id:
        return None

    url = build_standings_url(match_url, ts, match_id)
    html = fetch_standings_html(driver, url, wait_seconds)
    if not html:
        return None

    home_stats = TeamOverUnderStats()
    away_stats = TeamOverUnderStats()
    for line in lines:
        line_key = f"{line:.1f}".replace(".", "_")
        home_row = parse_team_over_under_row(html, home_id, line)
        away_row = parse_team_over_under_row(html, away_id, line)
        if home_row:
            _matches, over, under = home_row
            setattr(home_stats, f"over_{line_key}", str(over))
            setattr(home_stats, f"under_{line_key}", str(under))
        if away_row:
            _matches, over, under = away_row
            setattr(away_stats, f"over_{line_key}", str(over))
            setattr(away_stats, f"under_{line_key}", str(under))

    return home_stats, away_stats
