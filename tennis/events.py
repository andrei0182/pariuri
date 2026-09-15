from __future__ import annotations

import datetime as dt
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import OddsWinner, TennisMatch

logger = logging.getLogger(__name__)

# Endpoint-ul e identic cu cel confirmat la SuperBet (fotbal) — e un
# endpoint general, per-sport, nu specific unui sport. Ce NU e confirmat e
# TENNIS_SPORT_ID de mai jos.
EVENTS_URL = "https://production-superbet-offer-ro.freetls.fastly.net/v3/ro-RO/events"

# NEconfirmat — la fotbal a fost 5 (confirmat prin curl). Pentru tenis,
# trebuie găsit la fel: fie prin curl/inspect_page.py pe endpoint-ul de
# events cu diverse valori, fie citind din răspunsul unei pagini Superbet
# de tenis ce sport id trimite în request-urile ei XHR (DevTools Network).
TENNIS_SPORT_ID: int | None = None

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_session = requests.Session()
_session.headers.update({"User-Agent": _USER_AGENT})
_retry = Retry(total=5, backoff_factor=1.5, status_forcelist=[400, 429, 500, 502, 503, 504], respect_retry_after_header=True)
_session.mount("https://", HTTPAdapter(max_retries=_retry))
_session.mount("http://", HTTPAdapter(max_retries=_retry))


def _iso_utc(d: dt.date) -> str:
    """Identic cu SuperBet — midnight UTC, end-exclusive range (confirmat
    acolo că un endDate de 23:59:59.999 dă 400 Bad Request)."""
    return f"{d.isoformat()}T00:00:00.000Z"


def fetch_events(
    tournament_ids: list[int],
    date: dt.date,
    index: str = "active-prematch",
    timeout: float = 15.0,
) -> list[dict]:
    """Fetch evenimente brute pentru turneele date, pe o zi. Structura
    request-ului e copiată din SuperBet (confirmată acolo) — dar
    TENNIS_SPORT_ID trebuie completat mai jos înainte ca asta să funcționeze
    pentru tenis. Vezi parse_event() pentru conversia unui event în
    TennisMatch."""
    if TENNIS_SPORT_ID is None:
        raise RuntimeError(
            "TENNIS_SPORT_ID nu e confirmat încă — investighează cu "
            "tools/inspect_page.py sau curl înainte de a apela fetch_events()."
        )
    params = {
        "startDate": _iso_utc(date),
        "endDate": _iso_utc(date + dt.timedelta(days=1)),
        "index": index,
        "sports": TENNIS_SPORT_ID,
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


def parse_event(event: dict, tour: str = "", tournament: str = "") -> TennisMatch:
    """Convertește un event brut într-un TennisMatch.

    NEconfirmat: numele separatorului dintre jucători în event_name (la
    fotbal era "·"), numele market-ului de rezultat final (la fotbal era
    "Final" cu odds 1/X/2 — la tenis probabil un market similar dar cu doar
    1/2, fără "X", deoarece nu există egalitate). Rescrie logica de mai jos
    odată ce ai inspectat un răspuns real."""
    fixture = event.get("fixture", {})
    event_name = fixture.get("event_name", "")
    if "·" in event_name:
        player1, player2 = event_name.split("·", 1)
    else:
        player1, player2 = event_name, ""

    odds_winner = OddsWinner()
    for market in event.get("markets", []):
        # NEconfirmat: numele exact al market-ului — placeholder de mai jos.
        if market.get("name") not in ("Final", "Câștigător meci", "Learn me tenis"):
            continue
        for odd in market.get("odds", []):
            name = odd.get("metadata", {}).get("name")
            price = odd.get("price")
            if name == "1":
                odds_winner.player1 = price
            elif name == "2":
                odds_winner.player2 = price

    return TennisMatch(
        tour=tour,
        tournament=tournament,
        player1=player1.strip(),
        player2=player2.strip(),
        time_text=fixture.get("event_date", ""),
        status=event.get("inplay_stats_metadata", {}).get("status", ""),
        odds_winner=odds_winner,
        event_id=event.get("event_id"),
        match_url=f"https://superbet.ro/cote/tenis/{event.get('event_id')}" if event.get("event_id") else None,
    )


def fetch_events_for_all_tournaments(
    tournament_ids: list[int],
    date: dt.date,
    index: str = "active-prematch",
    workers: int = 8,
    timeout: float = 15.0,
) -> list[dict]:
    """Identic cu tiparul confirmat la SuperBet — o cerere per turneu, în
    paralel, în loc de a înghesui multe id-uri într-o singură cerere (acolo
    s-a confirmat că request-urile cu multe id-uri batched devin instabile)."""
    all_events: list[dict] = []

    def _fetch_one(tid: int) -> list[dict]:
        return fetch_events([tid], date, index=index, timeout=timeout)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_one, tid): tid for tid in tournament_ids}
        for future in as_completed(futures):
            tid = futures[future]
            try:
                events = future.result()
                all_events.extend(events)
            except Exception:
                logger.exception("fetch_events_for_all_tournaments: failed for tournament_id=%s", tid)

    return all_events
