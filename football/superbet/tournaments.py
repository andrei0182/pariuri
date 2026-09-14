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


def normalize_tournament_value(value: str | dict) -> list[int]:
    """The tournament map's values come in two confirmed shapes (2026-09-14):
    a plain numeric-string id ("104"), or — for ~49 entries — a dict with
    "tournamentIds": [...] (multiple underlying tournament ids merged under
    one display name, e.g. two Norway 2.Division groups shown as a single
    "Norvegia - 2.Division" competition). Always returns a list of ints.
    """
    if isinstance(value, dict):
        return [int(x) for x in value.get("tournamentIds", [])]
    return [int(value)]


def find_tournament(country_slug: str, league_slug: str) -> int | None:
    """Look up one tournament's id by its country and league slug, e.g.
    find_tournament("italia", "serie-a") -> 104. Returns None if not found.

    For a GROUPED entry (see normalize_tournament_value), returns only the
    first underlying id — use find_tournament_ids() instead if you need all
    of them (e.g. to fetch every match under a merged competition name).
    """
    key = f"fotbal---{country_slug}---{league_slug}"
    value = fetch_tournament_map().get(key)
    if value is None:
        return None
    ids = normalize_tournament_value(value)
    return ids[0] if ids else None


def find_tournament_ids(country_slug: str, league_slug: str) -> list[int]:
    """Like find_tournament, but returns ALL underlying ids for a grouped
    entry instead of just the first one. For a non-grouped entry, returns a
    single-item list."""
    key = f"fotbal---{country_slug}---{league_slug}"
    value = fetch_tournament_map().get(key)
    return normalize_tournament_value(value) if value is not None else []


def all_football_tournament_ids() -> list[int]:
    """Every underlying tournament id across all football entries (grouped
    entries expanded, duplicates removed) — for an "--all leagues" fetch."""
    ids: set[int] = set()
    for value in football_tournaments().values():
        ids.update(normalize_tournament_value(value))
    return sorted(ids)


def search_tournaments(query: str) -> dict[str, int]:
    """Case-insensitive substring search over football tournament slugs —
    useful for finding the right slug when you don't know it exactly, e.g.
    search_tournaments("italia") to see every Italian football competition.
    """
    query_lower = query.lower()
    return {k: v for k, v in football_tournaments().items() if query_lower in k.lower()}

_reverse_map_cache: dict[int, str] | None = None


def reverse_lookup(tournament_id: int) -> str | None:
    """id -> slug, e.g. 104 -> "fotbal---italia---serie-a" (cached). For a
    grouped entry, every underlying id maps back to the same slug."""
    global _reverse_map_cache
    if _reverse_map_cache is None:
        _reverse_map_cache = {}
        for slug, value in football_tournaments().items():
            for tid in normalize_tournament_value(value):
                _reverse_map_cache[tid] = slug
    return _reverse_map_cache.get(tournament_id)

