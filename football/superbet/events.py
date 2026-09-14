from __future__ import annotations

import datetime as dt
import logging

import requests

from .models import Match, Odds1X2, OddsOverUnder

logger = logging.getLogger(__name__)

EVENTS_URL = "https://production-superbet-offer-ro.freetls.fastly.net/v3/ro-RO/events"
FOOTBALL_SPORT_ID = 5  # CONFIRMED (2026-09-14) via curl — sports=5 in the events query
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_session = requests.Session()
_session.headers.update({"User-Agent": _USER_AGENT})


def _iso_utc(d: dt.date) -> str:
    """Midnight UTC for the given date, in the exact format the endpoint
    expects (confirmed via curl — an end-of-day 23:59:59.999 timestamp for
    endDate returned 400 Bad Request; use the next day's midnight instead
    for an end-exclusive range)."""
    return f"{d.isoformat()}T00:00:00.000Z"


def fetch_events(
    tournament_ids: list[int],
    date: dt.date,
    index: str = "active-prematch",
    timeout: float = 15.0,
) -> list[dict]:
    """Fetch raw event dicts for the given tournament(s) on a given date.

    CONFIRMED (2026-09-14) via curl: this endpoint needs no session/cookies,
    a plain GET works standalone. `index` is "active-prematch" for
    not-yet-started matches or "active-live" for in-progress ones (seen both
    in DevTools traffic) — CONFIRM whether a third value exists for
    already-finished matches, or whether completed-match odds simply aren't
    available here (would need Scorealarm or another endpoint instead).

    Returns the raw `events` list from the JSON response, unparsed — see
    parse_event() to convert one entry into a Match.
    """
    params = {
        "startDate": _iso_utc(date),
        "endDate": _iso_utc(date + dt.timedelta(days=1)),
        "index": index,
        "sports": FOOTBALL_SPORT_ID,
        "tournaments": ",".join(str(t) for t in tournament_ids),
    }
    try:
        resp = _session.get(EVENTS_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        result = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("fetch_events: request failed for tournaments=%s date=%s: %s", tournament_ids, date, exc)
        return []

    return result.get("events", [])


def parse_event(event: dict) -> Match:
    """Convert one raw event dict (from fetch_events) into a Match.

    CONFIRMED (2026-09-14) structure: event["fixture"]["event_name"] is
    "Home·Away" (separated by "·", not " - "); event["markets"] is a list of
    betting markets, where the market named "Final" (id 547 seen so far —
    CONFIRM this id is stable/global vs per-tournament) holds the 1X2 prices
    under odds[].metadata.name ("1"/"X"/"2") and odds[].price.
    """
    fixture = event.get("fixture", {})
    event_name = fixture.get("event_name", "")
    if "·" in event_name:
        home_team, away_team = event_name.split("·", 1)
    else:
        home_team, away_team = event_name, ""

    odds_1x2 = Odds1X2()
    for market in event.get("markets", []):
        if market.get("name") != "Final":
            continue
        for odd in market.get("odds", []):
            name = odd.get("metadata", {}).get("name")
            price = odd.get("price")
            if name == "1":
                odds_1x2.home = price
            elif name == "X":
                odds_1x2.draw = price
            elif name == "2":
                odds_1x2.away = price

    return Match(
        league="",  # filled in by the caller, which knows which tournament this came from
        home_team=home_team.strip(),
        away_team=away_team.strip(),
        time_text=fixture.get("event_date", ""),
        status=event.get("inplay_stats_metadata", {}).get("status", ""),
        odds_1x2=odds_1x2,
        match_url=f"https://superbet.ro/cote/fotbal/{event.get('event_id')}" if event.get("event_id") else None,
    )

EVENT_DETAIL_URL = "https://production-superbet-offer-ro.freetls.fastly.net/v2/ro-RO/events/{event_id}"


def fetch_event_detail(event_id: int, timeout: float = 15.0) -> dict | None:
    """Fetch the FULL per-match odds detail (all ~300 markets, ~3-4MB per
    match). CONFIRMED (2026-09-14) via curl: plain GET, no session needed.

    This is heavy — only call it for matches you actually need beyond the
    lightweight fetch_events() list (e.g. for Over/Under odds, which aren't
    included in that lighter endpoint's default "Final" market only).
    Returns None on any failure.
    """
    url = EVENT_DETAIL_URL.format(event_id=event_id)
    try:
        resp = _session.get(url, timeout=timeout)
        resp.raise_for_status()
        result = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("fetch_event_detail: request failed for event_id=%s: %s", event_id, exc)
        return None

    if result.get("error") or not result.get("data"):
        return None
    return result["data"][0]


def parse_over_under(event_detail: dict, line: float = 2.5) -> OddsOverUnder:
    """Extract Over/Under odds for one line from an event_detail dict (see
    fetch_event_detail). CONFIRMED (2026-09-14) structure: market name
    "Total goluri", with paired entries sharing a marketUuid — one with
    name "Sub {line}" (Under) and one "Peste {line}" (Over), e.g. "Sub 2.5"
    / "Peste 2.5" for the 2.5 line.
    """
    under_name = f"Sub {line:g}"
    over_name = f"Peste {line:g}"
    result = OddsOverUnder(line=line)

    for odd in event_detail.get("odds", []):
        if odd.get("marketName") != "Total goluri":
            continue
        name = odd.get("name")
        if name == over_name:
            result.over = odd.get("price")
        elif name == under_name:
            result.under = odd.get("price")

    return result
