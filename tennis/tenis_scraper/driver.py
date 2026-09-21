from __future__ import annotations

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


def build_driver(headless: bool = True, window_size: str = "1920,1080") -> webdriver.Chrome:
    """Headless Chrome, same pattern as the BetExplorer/SuperBet projects.

    STATUS: UNCONFIRMED whether either Superbet.ro's tennis pages or
    TennisExplorer.com actually need a real browser at all — run
    tools/inspect_page.py first. Per SuperBet's own experience, plain
    `requests` against a JSON API ended up being the answer for the odds
    side — don't reach for Selenium until inspect_page.py shows you need to.
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
