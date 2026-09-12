from __future__ import annotations

import logging

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from . import selectors as sel
from .models import TeamOverUnderStats

logger = logging.getLogger(__name__)

DEFAULT_WAIT = 15


def is_stats_eligible(driver: WebDriver) -> bool:
    """Step 7: a match only has Over/Under stats if its page has a standings table.

    Deliberately DOM-based rather than a competition-name heuristic ('Cup' in
    the name), since competitions like the Champions League have no
    standings table either despite not being literally a 'cup'.
    """
    return len(driver.find_elements(By.CSS_SELECTOR, sel.STANDINGS_TABLE)) > 0


def _read_cell(driver: WebDriver, css: str) -> str | None:
    elements = driver.find_elements(By.CSS_SELECTOR, css)
    return elements[0].text.strip() if elements and elements[0].text.strip() else None


def _click_and_wait_for_change(
    driver: WebDriver, tab_css: str, old_home_value: str | None, wait_seconds: int
) -> bool:
    """Click an Over/Under sub-tab and wait for the stats table content to actually change.

    Comparing against the previously read value (rather than a fixed sleep)
    is what step 8 asks for: each click re-renders the same DOM nodes, so a
    plain 'wait for element present' would pass instantly against stale text.
    """
    tabs = driver.find_elements(By.CSS_SELECTOR, tab_css)
    if not tabs:
        logger.warning("O/U sub-tab %s not found; selector needs verifying.", tab_css)
        return False
    tabs[0].click()

    try:
        WebDriverWait(driver, wait_seconds).until(
            lambda d: _read_cell(d, sel.OU_HOME_STATS_CELL) != old_home_value
            or old_home_value is None
        )
    except TimeoutException:
        logger.warning("Timed out waiting for O/U stats to refresh after clicking %s.", tab_css)
        return False
    return True


def extract_over_under_stats(
    driver: WebDriver, wait_seconds: int = DEFAULT_WAIT
) -> tuple[TeamOverUnderStats, TeamOverUnderStats]:
    """Step 8: click through Overall / 1.5, 2.5, 3.5 and read both teams' values each time."""
    home_stats = TeamOverUnderStats()
    away_stats = TeamOverUnderStats()

    baseline_home = _read_cell(driver, sel.OU_HOME_STATS_CELL)

    if _click_and_wait_for_change(driver, sel.OU_SUBTAB_1_5, None, wait_seconds):
        home_stats.over_1_5 = _read_cell(driver, sel.OU_HOME_STATS_CELL)
        away_stats.over_1_5 = _read_cell(driver, sel.OU_AWAY_STATS_CELL)
        last_home = home_stats.over_1_5
    else:
        last_home = baseline_home

    if _click_and_wait_for_change(driver, sel.OU_SUBTAB_2_5, last_home, wait_seconds):
        home_stats.over_2_5 = _read_cell(driver, sel.OU_HOME_STATS_CELL)
        away_stats.over_2_5 = _read_cell(driver, sel.OU_AWAY_STATS_CELL)
        last_home = home_stats.over_2_5
    else:
        home_stats.over_2_5 = _read_cell(driver, sel.OU_HOME_STATS_CELL)
        away_stats.over_2_5 = _read_cell(driver, sel.OU_AWAY_STATS_CELL)

    if _click_and_wait_for_change(driver, sel.OU_SUBTAB_3_5, last_home, wait_seconds):
        home_stats.over_3_5 = _read_cell(driver, sel.OU_HOME_STATS_CELL)
        away_stats.over_3_5 = _read_cell(driver, sel.OU_AWAY_STATS_CELL)
    else:
        home_stats.over_3_5 = _read_cell(driver, sel.OU_HOME_STATS_CELL)
        away_stats.over_3_5 = _read_cell(driver, sel.OU_AWAY_STATS_CELL)

    return home_stats, away_stats


def scrape_match_stats(
    driver: WebDriver, match_url: str, wait_seconds: int = DEFAULT_WAIT
) -> tuple[bool, TeamOverUnderStats | None, TeamOverUnderStats | None]:
    """Full Steps 7-8 pipeline for one match page. Returns (eligible, home_stats, away_stats)."""
    driver.get(match_url)
    try:
        WebDriverWait(driver, wait_seconds).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except TimeoutException:
        pass

    if not is_stats_eligible(driver):
        return False, None, None

    home_stats, away_stats = extract_over_under_stats(driver, wait_seconds)
    return True, home_stats, away_stats
