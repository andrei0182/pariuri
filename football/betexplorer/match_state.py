from __future__ import annotations

import re

from selenium.webdriver.remote.webelement import WebElement

from . import selectors as sel

_SCORE_RE = re.compile(sel.COMPLETED_SCORE_PATTERN)


def classify_status(row: WebElement) -> str:
    """Classify a match row as 'live', 'completed', or 'scheduled'.

    Order matters: a live match's score cell often already shows a partial
    score (e.g. "1:0"), so the live-indicator check must run before the
    completed-score check.
    """
    row_class = (row.get_attribute("class") or "")
    if sel.LIVE_ROW_CLASS in row_class:
        return "live"

    if row.find_elements("css selector", sel.LIVE_TIMER_CELL):
        return "live"

    score_text = _first_text(row, sel.SCORE_CELL)
    if score_text and _SCORE_RE.match(score_text.strip()):
        return "completed"

    return "scheduled"


def _first_text(row: WebElement, css: str) -> str | None:
    elements = row.find_elements("css selector", css)
    return elements[0].text if elements else None
