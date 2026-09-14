from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_session = requests.Session()
_session.headers.update({"User-Agent": _USER_AGENT})

FIXTURE_OVERVIEW_URL = "https://scorealarm-stats.freetls.fastly.net/v2/soccer/fixtures/overview/rosuperbetsport/ro-RO"
STANDINGS_URL = "https://scorealarm-stats.freetls.fastly.net/v2/soccer/competitions/standings/table/rosuperbetsport/ro-RO"
H2H_URL = "https://scorealarm-stats.freetls.fastly.net/v2/soccer/fixtures/h2h/rosuperbetsport/ro-RO"


def fetch_fixture_overview(event_id: int, timeout: float = 15.0) -> dict | None:
    """Fetch the Scorealarm fixture overview for one match — the entry
    point for everything else in this module, since it's where table_id
    (for standings) and team1.id/team2.id (for h2h) come from.

    CONFIRMED (2026-09-14) via curl: fixture-id is "ax:match:{event_id}"
    using the same event_id as the Superbet offer API (superbet_scraper.events)
    — no separate id mapping needed. Also includes prematch_stats: each
    team's season averages (goals scored/conceded, shots, xG, cards,
    corners per game) — useful on its own, independent of standings/h2h.
    """
    params = {"fixture-id": f"ax:match:{event_id}"}
    try:
        resp = _session.get(FIXTURE_OVERVIEW_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("fetch_fixture_overview: request failed for event_id=%s: %s", event_id, exc)
        return None


def extract_table_id(fixture_overview: dict) -> str | None:
    return fixture_overview.get("table_id", {}).get("value")


def extract_team_ids(fixture_overview: dict) -> tuple[str | None, str | None]:
    team1_id = fixture_overview.get("team1", {}).get("id")
    team2_id = fixture_overview.get("team2", {}).get("id")
    return team1_id, team2_id


def _row_values(data_group: dict) -> list[str | None]:
    """Pull the display_value (or draw_value, for the form column) out of
    one row's data[i] group."""
    out = []
    for item in data_group.get("values", []):
        v = item.get("value", {})
        out.append(v.get("display_value") or v.get("draw_value"))
    return out


def fetch_standings(table_id: str, timeout: float = 15.0) -> list[dict]:
    """Fetch the full league standings table (overall, not home/away split).

    CONFIRMED (2026-09-14) structure: response has "standings_groups"; each
    group has "rows_total" (the complete overall standings — 20 rows for a
    typical league, confirmed complete) alongside "rows_home"/"rows_away"
    splits (not used here). Each row's "data" is 3 groups matching
    "headers_total": [0]=played/goal_difference/points, [1]=wins/draws/
    losses, [2]=form (e.g. "W-W-W-D"). A league may have multiple standings
    groups (e.g. separate group-stage tables) — this uses the first group;
    revisit if a competition needs a specific one instead.
    """
    params = {"table-id": table_id}
    try:
        resp = _session.get(STANDINGS_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("fetch_standings: request failed for table_id=%s: %s", table_id, exc)
        return []

    groups = data.get("standings_groups", [])
    if not groups:
        return []

    rows = groups[0].get("rows_total", [])
    parsed = []
    for row in rows:
        row_data = row.get("data", [])
        played, goal_diff, points = (_row_values(row_data[0]) + [None, None, None])[:3] if len(row_data) > 0 else (None, None, None)
        wins, draws, losses = (_row_values(row_data[1]) + [None, None, None])[:3] if len(row_data) > 1 else (None, None, None)
        form = _row_values(row_data[2])[0] if len(row_data) > 2 and _row_values(row_data[2]) else None

        parsed.append({
            "rank": row.get("rank"),
            "team_name": row.get("competitor_name"),
            "team_id": row.get("competitor_id"),
            "country_code": row.get("country_code"),
            "played": played,
            "goal_difference": goal_diff,
            "points": points,
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "form": form,
        })
    return parsed


def fetch_h2h(team1_id: str, team2_id: str, timeout: float = 15.0) -> dict | None:
    """Fetch head-to-head history between two teams.

    CONFIRMED (2026-09-14) structure: "h2h_statistics" has aggregate
    win/draw/win counts (keys "team1"/"draw"/"team2") since "h2h_year_since";
    "h2h_events" is the full list of individual past matches with scores.
    """
    params = {"team1-id": team1_id, "team2-id": team2_id}
    try:
        resp = _session.get(H2H_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("fetch_h2h: request failed for %s vs %s: %s", team1_id, team2_id, exc)
        return None
