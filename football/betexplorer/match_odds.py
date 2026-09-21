from __future__ import annotations

import logging
import re

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import selectors as sel
from .models import Odds1X2, OddsOverUnder

logger = logging.getLogger(__name__)

# Matches a handicap block anywhere in the AJAX response and captures its
# two aggregate odds, e.g.:
#   <div data-all-handicap="2.50" class="... oddsComparisonAll__bestOdds"
#        data-hp-1="2.11" data-hp-2="1.74">
# Built per-call for the requested line rather than as a module constant,
# since the handicap value is an argument.
_HANDICAP_BLOCK_TEMPLATE = r'data-all-handicap="{line}"[^>]*data-hp-1="([\d.]*)"[^>]*data-hp-2="([\d.]*)"'

# CONFIRMED 2026-09-14 via curl: the 1X2 market's AJAX response has no
# handicap-style data-hp-1/data-hp-2 attributes (1X2 has no line/handicap
# concept) — instead the three aggregate odds sit in three consecutive
# elements inside the data-all-handicap="0" block, in 1/X/2 order:
#   <div class="oddsComparisonAll__odds_heads">
#     <div class="oddsComparisonAll__average_text" data-odd="1.75"></div>
#     <div class="oddsComparisonAll__average_text" data-odd="3.98"></div>
#     <div class="oddsComparisonAll__average_text" data-odd="3.89"></div>
_1X2_BLOCK_PATTERN = re.compile(
    r'data-all-handicap="0"[^>]*oddsComparisonAll__bestOdds.*?'
    r'oddsComparisonAll__odds_heads">\s*'
    r'<div class="oddsComparisonAll__average_text" data-odd="([\d.]*)"></div>'
    r'<div class="oddsComparisonAll__average_text" data-odd="([\d.]*)"></div>'
    r'<div class="oddsComparisonAll__average_text" data-odd="([\d.]*)"></div>',
    re.DOTALL,
)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_session = requests.Session()
_session.headers.update({"User-Agent": _USER_AGENT, "X-Requested-With": "XMLHttpRequest"})
_retry = Retry(total=8, backoff_factor=2.0, status_forcelist=[429, 500, 502, 503, 504], respect_retry_after_header=True)
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


def fetch_1x2_odds(match_id: str, timeout: float = 15.0) -> Odds1X2:
    """Fetch aggregate 1X2 odds for one match via the confirmed AJAX
    endpoint (see selectors.X12_AJAX_URL_TEMPLATE) — same pattern as
    fetch_over_under_odds, no session/cookies needed.

    CONFIRMED (2026-09-14): switched to this from scraping td.table-main__odds
    directly off the daily results list page — that DOM-based approach was
    unreliable in practice (0% coverage across an entire fresh run, even
    after adding an explicit wait for the odds cells' text to populate; see
    match_list.py's history). This endpoint works instantly and reliably
    via a plain HTTP request instead, the same lesson learned earlier today
    for the hit-rate stats widget.

    Returns Odds1X2() (all None) if the request fails or the expected
    pattern isn't found — this never raises.
    """
    url = sel.X12_AJAX_URL_TEMPLATE.format(match_id=match_id)
    try:
        resp = _session.get(url, timeout=timeout)
        resp.raise_for_status()
        result = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("fetch_1x2_odds: request failed for %s: %s", url, exc)
        return Odds1X2()

    if not isinstance(result, dict) or "odds" not in result:
        return Odds1X2()

    match = _1X2_BLOCK_PATTERN.search(result["odds"])
    if not match or not all(match.groups()):
        return Odds1X2()

    try:
        home, draw, away = (float(g) for g in match.groups())
        return Odds1X2(home=home, draw=draw, away=away)
    except ValueError:
        return Odds1X2()
