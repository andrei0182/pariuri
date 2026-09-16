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

# CONFIRMAT (2026-09-15) via curl, din fixture.sport_id pe un event real
# (WTA Guadalajara, tournament_id=81067).
TENNIS_SPORT_ID = 2

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
    """Fetch evenimente brute pentru turneele date, pe o zi. CONFIRMAT
    (2026-09-15) via curl, folosind tournament_id=81067 (WTA Guadalajara) —
    răspunsul include fixture.sport_id=2 și un market "Final" cu odds
    "1"/"2" (fără egalitate). Vezi parse_event() pentru conversia unui
    event în TennisMatch."""
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

    CONFIRMAT (2026-09-15) via curl, pe un event real de la WTA Guadalajara:
    - event_name separă jucătorii cu "·", identic cu fotbalul (ex.
      "Diane Parry·Peyton Stearns")
    - market-ul de rezultat final se numește "Final" (id 521), identic cu
      fotbalul, dar conține DOAR odds cu name "1"/"2" — nu există "X"
      (fără egalitate la tenis)
    - fixture.sport_id == 2 confirmă că evenimentul e de tenis (vezi
      TENNIS_SPORT_ID mai sus)
    """
    fixture = event.get("fixture", {})
    event_name = fixture.get("event_name", "")
    if "·" in event_name:
        player1, player2 = event_name.split("·", 1)
    else:
        player1, player2 = event_name, ""

    odds_winner = OddsWinner()
    for market in event.get("markets", []):
        if market.get("name") != "Final":
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


# ============================================================
# Market-uri extinse (minim 1 set, total seturi, total game-uri pe set)
# CONFIRMAT (2026-09-16) prin inspectia unui request real din browser -
# endpoint DIFERIT de fetch_events() de mai sus, e un stream
# text/event-stream (SSE), nu JSON simplu. Se cere per-eveniment (nu
# batch), deci NU il apelam automat in build_report pentru toate
# meciurile (ar fi sute de cereri suplimentare) - e opt-in via flag.
# ============================================================

import json as _json  # noqa: E402
from dataclasses import dataclass as _dataclass, field as _field  # noqa: E402

EXTENDED_MARKETS_URL = "https://production-superbet-offer-ro.freetls.fastly.net/v3/subscription/ro-RO/events"

# Nume de market CONFIRMATE (2026-09-16) pe un meci real (Frech vs Dolehide,
# event_id=14993956). Alte meciuri ar trebui sa aiba aceleasi id-uri de
# market (structura Superbet e per-sport, nu per-meci), dar NEconfirmat
# 100% ca id-urile sunt universale pentru toate turneele/tur-urile.
MARKET_ID_MIN_1_SET = 518  # jucator 1
MARKET_ID_MIN_1_SET_P2 = 522  # jucator 2 - market SEPARAT, nu acelasi id
MARKET_ID_TOTAL_SETS = 2392
MARKET_ID_SET_TOTAL_GAMES = 524  # partajat intre Setul 1 si Setul 2, distins prin specifiers.setnr


@_dataclass
class OddsMinOneSet:
    player1_yes: Optional[float] = None
    player2_yes: Optional[float] = None


@_dataclass
class OddsTotalSets:
    line: Optional[float] = None
    under: Optional[float] = None
    over: Optional[float] = None


@_dataclass
class SetGamesLine:
    set_number: int
    line: float
    under: Optional[float] = None
    over: Optional[float] = None


@_dataclass
class ExtendedMarkets:
    min_1_set: OddsMinOneSet = _field(default_factory=OddsMinOneSet)
    total_sets: OddsTotalSets = _field(default_factory=OddsTotalSets)
    set_games: list = _field(default_factory=list)  # list[SetGamesLine]


def fetch_extended_markets_raw(event_id: int, timeout: float = 10.0, max_bytes: int = 600_000) -> list[dict] | None:
    """Fetch toate market-urile unui eveniment prin endpoint-ul de
    subscription (SSE). CONFIRMAT: raspunsul e un stream care nu se
    inchide singur - citim un numar limitat de octeti si taiem conexiunea,
    apoi parsam prima linie "data:[...]" ca JSON. Daca max_bytes e prea mic
    pentru un meci cu foarte multe market-uri, JSON-ul iese incomplet si
    functia returneaza None (mareste max_bytes in acel caz)."""
    try:
        resp = _session.get(
            EXTENDED_MARKETS_URL,
            params={"events": str(event_id)},
            timeout=timeout,
            stream=True,
        )
    except requests.RequestException as exc:
        logger.warning("fetch_extended_markets_raw: request failed for event_id=%s: %s", event_id, exc)
        return None

    buf = b""
    try:
        for chunk in resp.iter_content(chunk_size=8192):
            buf += chunk
            if len(buf) > max_bytes:
                break
    except Exception as exc:
        logger.debug("fetch_extended_markets_raw: stream read stopped for event_id=%s: %s", event_id, exc)
    finally:
        resp.close()

    text = buf.decode("utf-8", errors="replace")
    line = text.split("\n")[0]
    if line.startswith("data:"):
        line = line[len("data:"):]

    try:
        data = _json.loads(line)
    except _json.JSONDecodeError:
        logger.warning("fetch_extended_markets_raw: JSON incomplet pentru event_id=%s (mareste max_bytes)", event_id)
        return None

    if not data:
        return None
    return data[0].get("markets", [])


def parse_extended_markets(markets: list[dict], player1_name: str, player2_name: str) -> ExtendedMarkets:
    """Extrage min-1-set / total seturi / total game-uri per set din lista
    bruta de market-uri. Potrivirea jucator-ului pentru market-ul "Minim 1
    set {Nume}" se face prin substring simplu in numele market-ului -
    functioneaza cat timp Superbet foloseste numele complet, ca in
    exemplul confirmat."""
    result = ExtendedMarkets()

    for m in markets:
        market_id = m.get("id")
        name = m.get("name", "")

        if market_id in (MARKET_ID_MIN_1_SET, MARKET_ID_MIN_1_SET_P2):
            da_price = next((o.get("price") for o in m.get("odds", []) if o.get("metadata", {}).get("name") == "Da"), None)
            if player1_name and player1_name in name:
                result.min_1_set.player1_yes = da_price
            elif player2_name and player2_name in name:
                result.min_1_set.player2_yes = da_price

        elif market_id == MARKET_ID_TOTAL_SETS:
            for o in m.get("odds", []):
                meta = o.get("metadata", {})
                line = meta.get("specifiers", {}).get("total")
                if line is not None:
                    result.total_sets.line = float(line)
                if meta.get("name", "").startswith("Sub"):
                    result.total_sets.under = o.get("price")
                elif meta.get("name", "").startswith("Peste"):
                    result.total_sets.over = o.get("price")

        elif market_id == MARKET_ID_SET_TOTAL_GAMES:
            for o in m.get("odds", []):
                meta = o.get("metadata", {})
                specifiers = meta.get("specifiers", {})
                setnr = specifiers.get("setnr")
                line = specifiers.get("total")
                if setnr is None or line is None:
                    continue
                set_num, line_val = int(setnr), float(line)
                existing = next((sg for sg in result.set_games if sg.set_number == set_num and sg.line == line_val), None)
                if existing is None:
                    existing = SetGamesLine(set_number=set_num, line=line_val)
                    result.set_games.append(existing)
                if meta.get("name", "").startswith("Sub"):
                    existing.under = o.get("price")
                elif meta.get("name", "").startswith("Peste"):
                    existing.over = o.get("price")

    return result


def fetch_and_parse_extended_markets(event_id: int, player1_name: str, player2_name: str) -> ExtendedMarkets | None:
    raw = fetch_extended_markets_raw(event_id)
    if raw is None:
        return None
    return parse_extended_markets(raw, player1_name, player2_name)
