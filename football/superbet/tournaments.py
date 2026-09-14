from __future__ import annotations

import logging
import re

import requests

logger = logging.getLogger(__name__)

TOURNAMENT_MAP_URL = "https://superbet.ro/static/offerMappings/sportTournamentMap_ro-RO.json"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_session = requests.Session()
_session.headers.update({"User-Agent": _USER_AGENT})

_cached_map: dict[str, int] | None = None


def fetch_tournament_map(timeout: float = 15.0) -> dict[str, int]:
    """Fetch (and cache for this process) the full slug -> tournament_id
    mapping. CONFIRMED (2026-09-14) via curl: static JSON, no auth/session
    needed. Slug format: "{sport}---{country}---{league}", e.g.
    "fotbal---italia---serie-a" -> 104. 12,696 total entries across all
    sports as of this writing; ~2,837 are football ("fotbal---...").
    """
    global _cached_map
    if _cached_map is not None:
        return _cached_map

    resp = _session.get(TOURNAMENT_MAP_URL, timeout=timeout)
    resp.raise_for_status()
    _cached_map = resp.json()
    return _cached_map


def football_tournaments() -> dict[str, int]:
    """Just the football ("fotbal---...") entries from the full map."""
    return {k: v for k, v in fetch_tournament_map().items() if k.startswith("fotbal---")}


def find_tournament(country_slug: str, league_slug: str) -> int | None:
    """Look up one tournament's id by its country and league slug, e.g.
    find_tournament("italia", "serie-a") -> 104. Returns None if not found.
    """
    key = f"fotbal---{country_slug}---{league_slug}"
    return fetch_tournament_map().get(key)


def search_tournaments(query: str) -> dict[str, int]:
    """Case-insensitive substring search over football tournament slugs —
    useful for finding the right slug when you don't know it exactly, e.g.
    search_tournaments("italia") to see every Italian football competition.
    """
    query_lower = query.lower()
    return {k: v for k, v in football_tournaments().items() if query_lower in k.lower()}
