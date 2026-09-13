from __future__ import annotations

import logging
import re

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import selectors as sel
from .models import OddsOverUnder

logger = logging.getLogger(__name__)

# Matches a handicap block anywhere in the AJAX response and captures its
# two aggregate odds, e.g.:
#   <div data-all-handicap="2.50" class="... oddsComparisonAll__bestOdds"
#        data-hp-1="2.11" data-hp-2="1.74">
# Built per-call for the requested line rather than as a module constant,
# since the handicap value is an argument.
_HANDICAP_BLOCK_TEMPLATE = r'data-all-handicap="{line}"[^>]*data-hp-1="([\d.]*)"[^>]*data-hp-2="([\d.]*)"'
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_session = requests.Session()
_session.headers.update({"User-Agent": _USER_AGENT, "X-Requested-With": "XMLHttpRequest"})
_retry = Retry(total=4, backoff_factor=1.0, status_forcelist=[429, 500, 502, 503, 504], respect_retry_after_header=True)
_session.mount("https://", HTTPAdapter(max_retries=_retry))
_session.mount("http://", HTTPAdapter(max_retries=_retry))


def extract_match_id(match_url: str) -> str | None:
    """Pull the match id out of a confirmed match URL, e.g.
    "https://www.betexplorer.com/football/england/premier-league/sunderland-arsenal/YoNI2r8F/"
    -> "YoNI2r8F". Relies on the id being the last non-empty path segment."""
    segments = [s for s in match_url.split("/") if s]
    return segments[-1] if segments else None


def fetch_over_under_odds(match_id: str, line: float = 2.5, timeout: float = 15.0) -> OddsOverUnder:
    """Fetch aggregate Over/Under odds for one match via the confirmed AJAX
    endpoint (see selectors.OU_AJAX_URL_TEMPLATE).

    CONFIRMED (2026-09-13) via curl: this endpoint needs no `ts` session
    token AND no browser cookies/session at all — a plain HTTP GET with a
    browser-like User-Agent works standalone, no page load required first.
    (Superseded a Selenium execute_async_script-based version that needed
    the driver to already have a betexplorer.com page loaded; no longer
    necessary.)

    Returns OddsOverUnder(line=line) with over/under left None if the line
    isn't offered for this match (not every match has every handicap) or the
    request fails for any reason — this never raises.
    """
    url = sel.OU_AJAX_URL_TEMPLATE.format(match_id=match_id)
    try:
        resp = _session.get(url, timeout=timeout)
        resp.raise_for_status()
        result = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("fetch_over_under_odds: request failed for %s: %s", url, exc)
        return OddsOverUnder(line=line)

    if not isinstance(result, dict) or "odds" not in result:
        return OddsOverUnder(line=line)

    html = result["odds"]
    handicap_str = f"{line:.2f}"
    pattern = re.compile(_HANDICAP_BLOCK_TEMPLATE.format(line=re.escape(handicap_str)))
    match = pattern.search(html)
    if not match or not match.group(1) or not match.group(2):
        return OddsOverUnder(line=line)

    try:
        return OddsOverUnder(line=line, over=float(match.group(1)), under=float(match.group(2)))
    except ValueError:
        return OddsOverUnder(line=line)
