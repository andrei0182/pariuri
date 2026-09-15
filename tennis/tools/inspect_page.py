"""Reconnaissance tool — rulează asta PRIMUL, înainte de a scrie orice logică
de scraping. Copiat identic din SuperBet/bet: verifică ce e disponibil real
în pagină înainte de a ghici selectori sau endpoint-uri.

Usage:
    python tools/inspect_page.py "https://superbet.ro/pariuri-sportive/tenis/atp/atp-us-open/toate"
    python tools/inspect_page.py "https://www.tennisexplorer.com/player/<nume>/"

Ce să cauți în output:
1. Vede `requests` simplu (fără browser) deja text de meci/cote/jucător?
   Dacă da, poate scapi complet de Selenium (așa a fost la cotele/stats-urile
   de fotbal de la BetExplorer și SuperBet, odată găsite endpoint-urile AJAX).
2. Dacă nu, ce vede Selenium în plus față de requests? Acel gol e ce are
   nevoie de execuție JS.
3. Orice request XHR/fetch vizibil manual în DevTools → Network, care arată
   spre un API JSON — asta ar permite să sari peste ambele abordări de
   scraping DOM, cel mai rapid și fiabil tipar confirmat la ambele proiecte
   anterioare.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests


def check_via_requests(url: str) -> None:
    print(f"\n=== Plain requests check: {url} ===")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"Request failed: {exc}")
        return

    text = resp.text
    print(f"Status: {resp.status_code}, length: {len(text)} chars")

    # Markeri generici pentru conținut de tenis (Superbet sau TennisExplorer)
    # — ajustează dacă investighezi altceva.
    markers = ["câştigă", "cote", "vs", "ranking", "H2H", "Head to head", "player"]
    found = [m for m in markers if m in text]
    print(f"Content markers found: {found if found else 'NONE — likely JS-rendered, needs a browser'}")

    with open("/tmp/tenis_requests_check.html", "w", encoding="utf-8") as f:
        f.write(text)
    print("Saved full response to /tmp/tenis_requests_check.html for manual inspection.")


def check_via_selenium(url: str) -> None:
    print(f"\n=== Selenium (real browser) check: {url} ===")
    try:
        from tenis_scraper.driver import build_driver
    except ImportError:
        print("Could not import build_driver — run this from the project root.")
        return

    driver = build_driver(headless=True)
    try:
        driver.get(url)
        import time
        time.sleep(5)  # let JS settle
        html = driver.page_source
        print(f"Selenium page_source length: {len(html)} chars")
        with open("/tmp/tenis_selenium_check.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("Saved full rendered HTML to /tmp/tenis_selenium_check.html for manual inspection.")
    finally:
        driver.quit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a page (Superbet tennis or TennisExplorer): requests vs Selenium.")
    parser.add_argument("url", help="URL de inspectat")
    parser.add_argument("--skip-selenium", action="store_true", help="Doar verificarea prin requests")
    args = parser.parse_args()

    check_via_requests(args.url)
    if not args.skip_selenium:
        check_via_selenium(args.url)


if __name__ == "__main__":
    main()
