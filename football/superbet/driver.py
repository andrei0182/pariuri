from __future__ import annotations

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


def build_driver(headless: bool = True, window_size: str = "1920,1080") -> webdriver.Chrome:
    """Headless Chrome, same pattern as the BetExplorer project.

    STATUS: UNCONFIRMED whether Superbet.ro actually needs a real browser at
    all — the initial recon in tools/inspect_page.py exists to answer that.
    If plain `requests` turns out to work (as it did for BetExplorer's odds
    and stats, once the right endpoints were found), prefer that — it's far
    faster and more reliable, per today's experience. Keep this around only
    for whatever step (if any) genuinely needs JS execution.
    """
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument(f"--window-size={window_size}")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)
