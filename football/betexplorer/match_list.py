from __future__ import annotations

import datetime as dt
import os
import logging
import time
from urllib.parse import urljoin

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from . import selectors as sel
from .consent import dismiss_overlays
from .match_state import classify_status
from .models import Match, Odds1X2

logger = logging.getLogger(__name__)

DEFAULT_WAIT = 15


def build_date_url(date: dt.date) -> str:
    return sel.DATE_URL_TEMPLATE.format(year=date.year, month=date.month, day=date.day)


def _wait_for_odds_text(driver: WebDriver, settle_seconds: float = 8.0) -> None:
    """Match rows (and their odds <td> cells) appear in the DOM as soon as
    presence_of_element_located(MATCH_ROW) succeeds, but the odds cells'
    TEXT populates asynchronously slightly after that (see ODDS_CELLS'
    comment in selectors.py) — on a fast page load, reading them
    immediately silently returns empty/None for every match's 1X2 odds.
    Waits for at least one odds cell to have non-empty text as a signal
    that rendering has caught up. Bounded and non-fatal: if the page
    genuinely has no odds populated yet for any match (e.g. a date far
    enough in the future that no bookmaker has posted odds), this times
    out quietly and extraction proceeds anyway rather than retrying the
    whole page load forever.
    """
    try:
        WebDriverWait(driver, settle_seconds).until(
            lambda d: any(
                el.text.strip() for el in d.find_elements(By.CSS_SELECTOR, sel.ODDS_CELLS)
            )
        )
    except TimeoutException:
        logger.info(
            "_wait_for_odds_text: no odds cell text appeared within %.0fs — "
            "proceeding anyway (may be a date with no odds posted yet)",
            settle_seconds,
        )


def load_date(driver: WebDriver, date: dt.date, wait_seconds: int = DEFAULT_WAIT, retries: int = 3) -> None:
    """Navigate to the match list for a given date and wait for rows to render.

    Retries the full page load up to `retries` times, since Chrome headless
    occasionally fails to render the table in time (or the session flakes)
    on the first attempt.
    """
    url = build_date_url(date)
    last_exc: TimeoutException | None = None

    for attempt in range(1, retries + 1):
        try:
            driver.get(url)
            dismiss_overlays(driver)
            WebDriverWait(driver, wait_seconds).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, sel.MATCH_ROW))
            )
            _wait_for_odds_text(driver)
            return  # success
        except TimeoutException as exc:
            # Covers both a page-load-level timeout from driver.get() itself
            # (Chrome's own renderer taking too long) and our own
            # WebDriverWait timing out waiting for match rows to appear —
            # either way, the fix is the same: reload and try again.
            last_exc = exc
            logger.warning(
                "load_date attempt %d/%d timed out for %s — retrying",
                attempt, retries, url,
            )
            if attempt < retries:
                time.sleep(3)

    debug_dir = os.environ.get("BETSCRAPER_DEBUG_DIR", ".")
    os.makedirs(debug_dir, exist_ok=True)
    html_path = os.path.join(debug_dir, "load_date_failure.html")
    png_path = os.path.join(debug_dir, "load_date_failure.png")
    try:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        driver.save_screenshot(png_path)
        logger.warning("Saved failure debug artifacts to %s and %s", html_path, png_path)
    except Exception:
        logger.exception("Could not save failure debug artifacts (page may have already navigated away).")

    raise TimeoutException(
        f"No match rows found at {url} after {retries} attempts ({wait_seconds}s each). "
        f"This means either (a) sel.MATCH_ROW ({sel.MATCH_ROW!r}) doesn't match this "
        f"page's real markup, (b) sel.DATE_URL_TEMPLATE doesn't produce a valid "
        f"date-filtered URL for this site, or (c) an overlay (age gate / cookie consent) "
        f"is still blocking the page and its selector needs updating in selectors.py, or "
        f"(d) the site is blocking/challenging this environment's IP specifically. "
        f"See {html_path} and {png_path} for exactly what was served. "
        f"Run `python tools/inspect_page.py {url!r}` locally to compare against a working environment."
    ) from last_exc


def _parse_float(text: str | None) -> float | None:
    if not text:
        return None
    text = text.strip().replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _row_text(row, css: str) -> str | None:
    elements = row.find_elements(By.CSS_SELECTOR, css)
    return elements[0].text.strip() if elements and elements[0].text.strip() else None


def _is_league_header_row(row) -> bool:
    """Confirmed: league-header rows have no distinguishing class (class=""
    on both header and match rows) — only structurally different: a header
    row's cells are <th>, a match row's are <td>."""
    return len(row.find_elements(By.CSS_SELECTOR, sel.LEAGUE_HEADER_ROW)) > 0


def _split_team_pair(text: str) -> tuple[str, str]:
    """Confirmed format: "Home Team - Away Team" in one <a> element's text."""
    if " - " in text:
        home, away = text.split(" - ", 1)
        return home.strip(), away.strip()
    return text.strip(), ""


def _extract_match_row(row) -> tuple[str, str, str, str | None] | None:
    """Pull (time, home, away, match_url) from a confirmed match row, or
    None if this row isn't a match row (ad banner, spacer, etc.)."""
    link_els = row.find_elements(By.CSS_SELECTOR, sel.TEAM_LINK_CELL)
    if not link_els:
        return None
    team_text = link_els[0].text.strip()
    if not team_text:
        return None
    home, away = _split_team_pair(team_text)
    if not home:
        return None
    time_text = _row_text(row, sel.TIME_CELL) or ""
    match_url = urljoin(sel.BASE_URL, link_els[0].get_attribute("href"))
    return time_text, home, away, match_url


def extract_matches_1x2(driver: WebDriver, date: dt.date) -> list[Match]:
    """Parse the currently loaded page's match table.

    Confirmed: /football/results/?year=&month=&day= mixes two row kinds for
    that date — completed (or in-progress) matches with a result cell
    (SCORE_CELL/PARTIAL_SCORE_CELL, no odds), and later-that-day matches that
    haven't kicked off yet (ODDS_CELLS, no result). Branch on which is
    present per row rather than assuming one for the whole page.

    `date` is the day this page was loaded for (the --date argument) — it's
    stamped onto every Match since the client's template requires a "Match
    Date" column and nothing on the row itself carries the calendar date.
    """
    matches: list[Match] = []
    current_league = ""
    rows = driver.find_elements(By.CSS_SELECTOR, sel.MATCH_ROW)

    for row in rows:
        if _is_league_header_row(row):
            league_name = _row_text(row, sel.LEAGUE_HEADER_NAME_CELL)
            if league_name:
                current_league = league_name
            continue

        parsed = _extract_match_row(row)
        if parsed is None:
            continue
        time_text, home, away, match_url = parsed

        score_cells = row.find_elements(By.CSS_SELECTOR, sel.SCORE_CELL)
        if score_cells:
            score = score_cells[0].text.strip() or None
            partial_score = _row_text(row, sel.PARTIAL_SCORE_CELL)
            odds = Odds1X2()
        else:
            score = _row_text(row, sel.LIVE_SCORE_CELL)  # best-effort — format unconfirmed, likely None until caught with an actual goal
            partial_score = None
            odds_cells = row.find_elements(By.CSS_SELECTOR, sel.ODDS_CELLS)
            odds = Odds1X2(
                home=_parse_float(odds_cells[0].text) if len(odds_cells) > 0 else None,
                draw=_parse_float(odds_cells[1].text) if len(odds_cells) > 1 else None,
                away=_parse_float(odds_cells[2].text) if len(odds_cells) > 2 else None,
            )

        status = classify_status(row)

        matches.append(
            Match(
                league=current_league,
                home_team=home,
                away_team=away,
                time_text=time_text,
                status=status,
                date=date,
                score=score,
                partial_score=partial_score,
                match_url=match_url,
                odds_1x2=odds,
            )
        )

    return matches


def scrape_day(driver: WebDriver, date: dt.date) -> list[Match]:
    """Load the day's match list and extract 1X2 odds.

    Over/Under odds are deliberately NOT fetched here. An earlier assumption
    that O/U 2.5 lived on this list page behind a view-switch dropdown was
    wrong — that dropdown doesn't exist in this page's real markup. O/U 2.5
    odds are instead fetched per-match via a confirmed AJAX endpoint; see
    betscraper.match_odds.fetch_over_under_odds, wired in through
    betscraper.match_stats.scrape_match_stats (used when --with-stats is
    passed to main.py).
    """
    load_date(driver, date)
    return extract_matches_1x2(driver, date)
