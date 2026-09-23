"""One-off: descarca pagini TennisExplorer reale in tools/samples/, ca sa
putem scrie parsere pe structura CONFIRMATA (nu presupusa) pentru:
- H2H (Baez vs Brooksby au 2 meciuri directe in 2026)
- suprafata meciului curent (header match-detail / pagina turneului)
- pagina de jucator (lista completa de meciuri: suprafata, adversar, data)
- pagina de rezultate zilnice (sursa pentru backtest)

Rulat din CI (proxy-ul sesiunii de dezvoltare blocheaza tennisexplorer.com).
Se sterge dupa ce parserele sunt scrise."""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tenis_scraper.tennisexplorer import BASE_URL, _session  # noqa: E402

OUT = Path(__file__).resolve().parent / "samples"

MATCHES = {
    "match_baez_brooksby": 3329361,     # terminat, H2H 2-0 Baez, hard (Chengdu)
    "match_ivanov_lemaitre": 3330420,   # terminat, ITF W50 Yecla
    "match_arifullina_ruchkina": 3331278,
}
RESULTS_PAGES = {
    "results_atp_2026-09-21": "/results/?type=atp-single&year=2026&month=09&day=21",
    "results_wta_2026-09-21": "/results/?type=wta-single&year=2026&month=09&day=21",
}


def fetch(path: str) -> str | None:
    url = path if path.startswith("http") else BASE_URL + path
    try:
        resp = _session.get(url, timeout=20)
        resp.raise_for_status()
        print(f"OK   {url} ({len(resp.text)} bytes)")
        return resp.text
    except Exception as exc:  # noqa: BLE001 - one-off, vrem doar sa logam
        print(f"FAIL {url}: {exc}")
        return None


def save(name: str, html: str) -> None:
    (OUT / f"{name}.html").write_text(html, encoding="utf-8")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    followed: set[str] = set()
    for name, match_id in MATCHES.items():
        html = fetch(f"/match-detail/?id={match_id}")
        time.sleep(1)
        if html is None:
            continue
        save(name, html)
        # urmam primul link de jucator si linkul de turneu, doar de pe primul meci
        if name != "match_baez_brooksby":
            continue
        player_links = re.findall(r'href="(/player/[^"]+)"', html)
        tournament_links = re.findall(r'href="(/[a-z0-9-]+/20\d\d/[^"]*)"', html)
        for label, links in (("player", player_links[:2]), ("tournament", tournament_links[:1])):
            for i, link in enumerate(links):
                if link in followed:
                    continue
                followed.add(link)
                page = fetch(link)
                time.sleep(1)
                if page is not None:
                    save(f"{label}_{i}", page)
    for name, path in RESULTS_PAGES.items():
        html = fetch(path)
        time.sleep(1)
        if html is not None:
            save(name, html)


if __name__ == "__main__":
    main()
