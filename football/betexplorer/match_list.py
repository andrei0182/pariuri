from __future__ import annotations

import datetime as dt
import logging
from urllib.parse import urljoin

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from . import selectors as sel
from .match_state import classify_status
from .models import Match, Odds1X2, OddsOverUnder

logger = logging.getLogger(__name__)

DEFAULT_WAIT = 15


def build_date_url(date: dt.date) -> str:
    return sel.DATE_URL_TEMPLATE.format(year=date.year, month=date.month, day=date.day)


def load_date(driver: WebDriver, date: dt.date, wait_seconds: int = DEFAULT_WAIT) -> None:
    """Navigate to the match list for a given date and wait for rows to render."""
    url = build_date_url(date)
    driver.get(url)
    WebDriverWait(driver, wait_seconds).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, sel.MATCH_ROW))
    )


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


def extract_matches_1x2(driver: WebDriver) -> list[Match]:
    """Parse the currently loaded page's match table assuming the 1X2 odds view is active."""
    matches: list[Match] = []
    current_league = ""
    rows = driver.find_elements(By.CSS_SELECTOR, sel.MATCH_ROW)

    for row in rows:
        if "table-main__head" in (row.get_attribute("class") or ""):
            current_league = row.text.strip()
            continue

        home = _row_text(row, sel.TEAM_HOME_CELL)
        away = _row_text(row, sel.TEAM_AWAY_CELL)
        if not home:
            continue  # not a match row (ad banner, spacer, etc.)

        time_text = _row_text(row, sel.TIME_OR_STATUS_CELL) or ""
        score = _row_text(row, sel.SCORE_CELL)
        status = classify_status(row)

        odds_cells = row.find_elements(By.CSS_SELECTOR, sel.ODDS_CELLS)
        odds = Odds1X2(
            home=_parse_float(odds_cells[0].text) if len(odds_cells) > 0 else None,
            draw=_parse_float(odds_cells[1].text) if len(odds_cells) > 1 else None,
            away=_parse_float(odds_cells[2].text) if len(odds_cells) > 2 else None,
        )

        link_els = row.find_elements(By.CSS_SELECTOR, sel.MATCH_LINK)
        match_url = urljoin(sel.BASE_URL, link_els[0].get_attribute("href")) if link_els else None

        matches.append(
            Match(
                league=current_league,
                home_team=home,
                away_team=away or "",
                time_text=time_text,
                status=status,
                score=score,
                match_url=match_url,
                odds_1x2=odds,
            )
        )

    return matches


def switch_to_over_under(driver: WebDriver, wait_seconds: int = DEFAULT_WAIT) -> bool:
    """Click the odds-view control to switch from 1X2 to Over/Under 2.5.

    Returns False (and leaves the page untouched) if the control isn't found —
    callers should treat that as "O/U odds unavailable for this view" rather
    than crash the whole run.
    """
    dropdowns = driver.find_elements(By.CSS_SELECTOR, sel.ODDS_VIEW_DROPDOWN)
    if not dropdowns:
        logger.warning("Odds-view dropdown not found; selector needs verifying (see selectors.py).")
        return False

    rows_before = driver.find_elements(By.CSS_SELECTOR, sel.MATCH_ROW)
    anchor = rows_before[0] if rows_before else None

    options = driver.find_elements(By.CSS_SELECTOR, sel.ODDS_VIEW_OPTION_OU25)
    if not options:
        logger.warning("Over/Under 2.5 option not found; selector needs verifying (see selectors.py).")
        return False
    options[0].click()

    try:
        if anchor is not None:
            WebDriverWait(driver, wait_seconds).until(EC.staleness_of(anchor))
        WebDriverWait(driver, wait_seconds).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, sel.MATCH_ROW))
        )
    except TimeoutException:
        logger.warning("Timed out waiting for Over/Under view to refresh.")
        return False
    return True


def extract_matches_ou(driver: WebDriver) -> dict[tuple[str, str, str], OddsOverUnder]:
    """Parse the currently loaded page's match table assuming the Over/Under 2.5 view is active.

    Returns a dict keyed the same way as Match.match_key() so results can be
    merged back onto the 1X2 list.
    """
    ou_by_key: dict[tuple[str, str, str], OddsOverUnder] = {}
    rows = driver.find_elements(By.CSS_SELECTOR, sel.MATCH_ROW)

    for row in rows:
        if "table-main__head" in (row.get_attribute("class") or ""):
            continue

        home = _row_text(row, sel.TEAM_HOME_CELL)
        away = _row_text(row, sel.TEAM_AWAY_CELL)
        if not home:
            continue

        time_text = _row_text(row, sel.TIME_OR_STATUS_CELL) or ""
        key = (home.strip().lower(), (away or "").strip().lower(), time_text.strip())

        odds_cells = row.find_elements(By.CSS_SELECTOR, sel.ODDS_CELLS)
        ou_by_key[key] = OddsOverUnder(
            line=2.5,
            over=_parse_float(odds_cells[0].text) if len(odds_cells) > 0 else None,
            under=_parse_float(odds_cells[1].text) if len(odds_cells) > 1 else None,
        )

    return ou_by_key


def merge_ou_into_matches(
    matches: list[Match], ou_by_key: dict[tuple[str, str, str], OddsOverUnder]
) -> None:
    for match in matches:
        ou = ou_by_key.get(match.match_key())
        if ou is not None:
            match.odds_ou = ou


def scrape_day(driver: WebDriver, date: dt.date) -> list[Match]:
    """Full Steps 3-6 pipeline for a single day: load page, get 1X2, switch view, get O/U, merge."""
    load_date(driver, date)
    matches = extract_matches_1x2(driver)

    if switch_to_over_under(driver):
        ou_by_key = extract_matches_ou(driver)
        merge_ou_into_matches(matches, ou_by_key)
    else:
        logger.warning("Skipping Over/Under merge for %s — view switch failed.", date)

    return matches
