from __future__ import annotations

from selenium.webdriver.remote.webelement import WebElement

from . import selectors as sel


def classify_status(row: WebElement) -> str:
    """Classify a match row as 'live', 'completed', or 'scheduled'.

    CONFIRMED: a live row carries a data-live="<match_id>" attribute
    directly on the <tr> — not a CSS class, which was the original (wrong)
    guess. Checked first since a live match's row can also contain
    leftover score-looking markup that would otherwise misclassify it as
    completed.
    """
    if row.get_attribute(sel.LIVE_ROW_ATTR):
        return "live"

    if row.find_elements("css selector", sel.SCORE_CELL):
        return "completed"

    return "scheduled"
