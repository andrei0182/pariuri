from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

# Copiat identic din SuperBet — același fișier JSON static conține toate
# sporturile, nu doar fotbal (SuperBet îl filtra pe "fotbal---").
TOURNAMENT_MAP_URL = "https://superbet.ro/static/offerMappings/sportTournamentMap_ro-RO.json"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# CONFIRMAT (2026-09-15) via curl direct pe sportTournamentMap_ro-RO.json —
# 3759 intrări "tenis---..." (atenție: "tenis-de-masa---..." e alt sport,
# trebuie filtrat separat cu startswith("tenis---"), nu startswith("tenis")).
# Tur-urile reale găsite sunt mult mai granulare decât presupusesem inițial:
TENNIS_TOURS = (
    "atp", "wta", "wta-125", "challenger",
    "itf-m", "itf-f",  # ITF separat pe gen, nu un singur "itf"
    "utr-m", "utr-f",
    "cupa-davis", "billie-jean-king-cup", "united-cup",
    "juniori", "meciuri-demonstrative",
    "simulated-reality", "simulated-reality-f",
)

_session = requests.Session()
_session.headers.update({"User-Agent": _USER_AGENT})

_cached_map: dict[str, int] | None = None


def fetch_tournament_map(timeout: float = 15.0) -> dict[str, int]:
    """Fetch (și cache pentru acest proces) tot mapping-ul slug -> tournament_id.
    Copiat identic din SuperBet — logica de fetch nu se schimbă, doar filtrarea."""
    global _cached_map
    if _cached_map is not None:
        return _cached_map

    resp = _session.get(TOURNAMENT_MAP_URL, timeout=timeout)
    resp.raise_for_status()
    _cached_map = resp.json()
    return _cached_map


def tennis_tournaments() -> dict[str, int]:
    """Doar intrările de tenis ("tenis---...") din mapping-ul complet.
    CONFIRMAT (2026-09-15): folosește "tenis---" (cu triplă liniuță), NU
    doar "tenis" — altfel prinde și "tenis-de-masa---..." (alt sport)."""
    return {k: v for k, v in fetch_tournament_map().items() if k.startswith("tenis---")}


def normalize_tournament_value(value) -> list[int]:
    """Identic cu SuperBet — valorile pot fi un id simplu sau un dict cu
    "tournamentIds" (intrări grupate)."""
    if isinstance(value, dict):
        return [int(x) for x in value.get("tournamentIds", [])]
    return [int(value)]


def find_tournament(tour: str, tournament_slug: str) -> int | None:
    """Caută un turneu după tur (atp/wta/...) și slug, ex.
    find_tournament("atp", "atp-us-open"). Returnează None dacă nu găsește."""
    key = f"tenis---{tour}---{tournament_slug}"
    value = fetch_tournament_map().get(key)
    if value is None:
        return None
    ids = normalize_tournament_value(value)
    return ids[0] if ids else None


def search_tournaments(query: str) -> dict[str, int]:
    """Căutare substring case-insensitive peste slug-urile de tenis — util
    pentru a găsi slug-ul exact când nu-l știi, ex. search_tournaments("us-open")."""
    query_lower = query.lower()
    return {k: v for k, v in tennis_tournaments().items() if query_lower in k.lower()}


def all_tennis_tournament_ids(tours: tuple[str, ...] = TENNIS_TOURS) -> list[int]:
    """Toate id-urile de turnee de tenis, opțional filtrate pe tur-uri
    specifice (ex. doar "atp" și "wta", excluzând "challenger"/"itf")."""
    ids: set[int] = set()
    for slug, value in tennis_tournaments().items():
        parts = slug.split("---")
        if len(parts) >= 2 and parts[1] not in tours:
            continue
        ids.update(normalize_tournament_value(value))
    return sorted(ids)
