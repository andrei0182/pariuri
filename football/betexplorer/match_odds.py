from __future__ import annotations

import re

from selenium.webdriver.remote.webdriver import WebDriver

from . import selectors as sel
from .models import OddsOverUnder

# Matches a handicap block anywhere in the AJAX response and captures its
# two aggregate odds, e.g.:
#   <div data-all-handicap="2.50" class="... oddsComparisonAll__bestOdds"
#        data-hp-1="2.11" data-hp-2="1.74">
# Built per-call for the requested line rather than as a module constant,
# since the handicap value is an argument.
_HANDICAP_BLOCK_TEMPLATE = r'data-all-handicap="{line}"[^>]*data-hp-1="([\d.]*)"[^>]*data-hp-2="([\d.]*)"'


def extract_match_id(match_url: str) -> str | None:
    """Pull the match id out of a confirmed match URL, e.g.
    "https://www.betexplorer.com/football/england/premier-league/sunderland-arsenal/YoNI2r8F/"
    -> "YoNI2r8F". Relies on the id being the last non-empty path segment."""
    segments = [s for s in match_url.split("/") if s]
    return segments[-1] if segments else None


def fetch_over_under_odds(
    driver: WebDriver, match_id: str, line: float = 2.5, wait_seconds: float = 15.0
) -> OddsOverUnder:
    """Fetch aggregate Over/Under odds for one match via the confirmed AJAX
    endpoint (see selectors.OU_AJAX_URL_TEMPLATE).

    CONFIRMED to need no `ts` session token, but the driver must already have
    a betexplorer.com page loaded (age-gate/consent cookies set) before
    calling this — it doesn't navigate anywhere itself, just calls fetch()
    in the current page's origin via execute_async_script.

    Returns OddsOverUnder(line=line) with over/under left None if the line
    isn't offered for this match (not every match has every handicap) or the
    request fails for any reason — this never raises.
    """
    url = sel.OU_AJAX_URL_TEMPLATE.format(match_id=match_id)
    script = """
    var callback = arguments[arguments.length - 1];
    fetch(arguments[0], {headers: {'X-Requested-With': 'XMLHttpRequest'}, credentials: 'same-origin'})
        .then(function(r) { return r.json(); })
        .then(function(data) { callback(data); })
        .catch(function(err) { callback({error: String(err)}); });
    """
    try:
        driver.set_script_timeout(wait_seconds)
        result = driver.execute_async_script(script, url)
    except Exception:
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
