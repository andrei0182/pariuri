from __future__ import annotations

import logging

from selenium.common.exceptions import ElementClickInterceptedException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from . import selectors as sel

logger = logging.getLogger(__name__)


def _try_click(driver: WebDriver, by: str, value: str, wait_seconds: float) -> bool:
    try:
        el = WebDriverWait(driver, wait_seconds).until(
            EC.element_to_be_clickable((by, value))
        )
    except TimeoutException:
        return False
    try:
        el.click()
    except ElementClickInterceptedException:
        # Something (another overlay) is on top of it — try a JS click as a fallback.
        driver.execute_script("arguments[0].click();", el)
    return True


def dismiss_overlays(driver: WebDriver, wait_seconds: float = 3.0) -> None:
    """Best-effort dismissal of the age-gate and cookie-consent overlays.

    Call this right after driver.get(...) and before waiting for the match
    table — both overlays can sit on top of the page and block every other
    selector from ever matching an interactable element. Every selector here
    is a guess (see selectors.py); failing to find one is not an error, so
    this never raises — it just logs and moves on.
    """
    for css in sel.AGE_GATE_CONFIRM_BUTTONS:
        if _try_click(driver, By.CSS_SELECTOR, css, wait_seconds):
            logger.info("Dismissed age gate via selector: %s", css)
            break
    else:
        if _try_click(driver, By.XPATH, sel.AGE_GATE_CONFIRM_XPATH, wait_seconds):
            logger.info("Dismissed age gate via text-match fallback.")
        else:
            logger.debug("No age-gate overlay found (or selectors are stale).")

    for css in sel.COOKIE_CONSENT_BUTTONS:
        if _try_click(driver, By.CSS_SELECTOR, css, wait_seconds):
            logger.info("Dismissed cookie-consent banner via selector: %s", css)
            break
    else:
        logger.debug("No cookie-consent banner found (or selectors are stale).")
