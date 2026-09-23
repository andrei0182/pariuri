"""Istoricul de rezultate pentru ratingul Elo: toate meciurile de simplu
terminate normal de pe paginile /results/ ale TennisExplorer (atp-single si
wta-single, care includ Challenger / ITF / WTA 125), plus suprafata fiecarui
turneu, luata o singura data de pe pagina turneului si tinuta in cache.

Fisiere (comise in repo, actualizate incremental):
- data/results.csv.gz         - un rand per meci (comprimat, pandas il citeste direct)
- data/tournament_surfaces.csv - slug turneu -> suprafata

Structura CONFIRMATA 2026-09-23 pe pagini reale (tests/fixtures/):
- /results/: table.result, rand "head" per turneu (link /slug/an/tur/), apoi
  2 <tr> per meci (id rN si rNb), castigatorul MEREU primul (414/414),
  td.result = seturi castigate, 5 td.score, cote H/A pe primul rand.
  Walkover / abandon: "1 0" cu scor gol sau incomplet - le sarim.
- pagina turneului: div.box.boxBasic.lGray cu "(1,210,115 $, hard, men)".

Rulare (din CI - proxy-ul sesiunii de dezvoltare blocheaza TennisExplorer):
    python history.py --days 180     # completeaza zilele care lipsesc
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

from tenis_scraper import tennisexplorer as te

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
RESULTS_CSV = DATA_DIR / "results.csv.gz"
SURFACES_CSV = DATA_DIR / "tournament_surfaces.csv"
RESULTS_URL = te.BASE_URL + "/results/"
TOUR_TYPES = ("atp-single", "wta-single")
SURFACES = ("hard", "clay", "grass", "indoors", "carpet")


@dataclass
class HistoricMatch:
    date: str  # ISO
    tour_type: str
    tournament: str
    tournament_slug: str  # ex. "/chengdu/2026/atp-men/"
    match_id: int
    winner_slug: str  # ex. "/player/brooksby/" - identificator unic de jucator
    loser_slug: str
    winner_name: str
    loser_name: str
    score: str  # din perspectiva castigatorului, ex. "7-5 7-5"
    odds_winner: float | None
    odds_loser: float | None


def _cell_games(cell) -> int | None:
    text = "".join(t for t in cell.find_all(string=True, recursive=False)).strip()
    return int(text) if text.isdigit() else None


def _set_finished(a: int, b: int) -> bool:
    high, low = max(a, b), min(a, b)
    return (high >= 6 and high - low >= 2) or (high == 7 and low >= 5)


def _player(row) -> tuple[str, str] | None:
    cell = row.find("td", class_="t-name")
    link = cell.find("a", href=re.compile(r"^/player/")) if cell else None
    if link is None or "/" in link.get_text():
        return None
    return link["href"], link.get_text(strip=True)


def parse_results_page(html: str, date: dt.date, tour_type: str) -> list[HistoricMatch]:
    """Meciurile de simplu terminate normal (fara walkover/abandon)."""
    soup = BeautifulSoup(html, "lxml")
    matches: list[HistoricMatch] = []
    for table in soup.find_all("table", class_="result"):
        tournament, slug = "", ""
        for tr in table.find_all("tr"):
            if "head" in (tr.get("class") or []):
                link = tr.find("a", href=True)
                if link is not None:
                    tournament, slug = link.get_text(strip=True), link["href"]
                continue
            row_id = tr.get("id") or ""
            if not re.fullmatch(r"r\d+", row_id):
                continue
            second = table.find("tr", id=row_id + "b")
            detail_link = tr.find("a", href=re.compile(r"/match-detail/"))
            if second is None or detail_link is None:
                continue
            p1, p2 = _player(tr), _player(second)
            if p1 is None or p2 is None:
                continue
            try:
                sets1 = int(tr.find("td", class_="result").get_text(strip=True))
                sets2 = int(second.find("td", class_="result").get_text(strip=True))
            except (AttributeError, ValueError):
                continue
            games1 = [_cell_games(c) for c in tr.find_all("td", class_="score")]
            games2 = [_cell_games(c) for c in second.find_all("td", class_="score")]
            sets = [(a, b) for a, b in zip(games1, games2) if a is not None and b is not None]
            if sets1 <= sets2 or sets1 < 2 or len(sets) != sets1 + sets2:
                continue  # walkover, abandon sau scor incomplet
            if not all(_set_finished(a, b) for a, b in sets[:-1]):
                continue
            last = sets[-1]
            # setul decisiv poate fi super tiebreak (ex. 10-8) - acceptat daca e castigat la 2 diferenta
            if not (_set_finished(*last) or (max(last) >= 10 and abs(last[0] - last[1]) >= 2)):
                continue
            odds = [c.get_text(strip=True) for c in tr.find_all("td", class_=["course", "coursew"])]
            odds_f = [float(o) for o in odds if re.fullmatch(r"\d+\.\d+", o)]
            match_id = te.find_match_id_from_gamedetail_link(detail_link["href"])
            if match_id is None:
                continue
            matches.append(HistoricMatch(
                date=date.isoformat(), tour_type=tour_type, tournament=tournament, tournament_slug=slug,
                match_id=match_id, winner_slug=p1[0], loser_slug=p2[0], winner_name=p1[1], loser_name=p2[1],
                score=" ".join(f"{a}-{b}" for a, b in sets),
                odds_winner=odds_f[0] if len(odds_f) == 2 else None,
                odds_loser=odds_f[1] if len(odds_f) == 2 else None,
            ))
    return matches


def parse_tournament_surface(html: str) -> str:
    """Din "(1,210,115 $, hard, men)" -> "Hard". "" daca nu apare."""
    soup = BeautifulSoup(html, "lxml")
    for box in soup.select("div.box.boxBasic.lGray"):
        m = re.search(r"\(([^)]*)\)", box.get_text(" ", strip=True))
        if not m:
            continue
        for part in m.group(1).split(","):
            if part.strip().lower() in SURFACES:
                return part.strip().capitalize()
    return ""


def _get(url: str, params: dict | None = None) -> str | None:
    try:
        resp = te._session.get(url, params=params, timeout=20)
        resp.raise_for_status()
        return resp.text
    except Exception as exc:  # noqa: BLE001
        logger.warning("GET %s %s: %s", url, params, exc)
        return None


def load_results() -> pd.DataFrame:
    if RESULTS_CSV.exists():
        return pd.read_csv(RESULTS_CSV)
    return pd.DataFrame(columns=list(HistoricMatch.__dataclass_fields__))


def load_surfaces() -> dict[str, str]:
    if SURFACES_CSV.exists():
        df = pd.read_csv(SURFACES_CSV, keep_default_na=False)
        return dict(zip(df["tournament_slug"], df["surface"]))
    return {}


def _save(results: pd.DataFrame, new_rows: list[dict]) -> pd.DataFrame:
    results = pd.concat([results, pd.DataFrame(new_rows)], ignore_index=True)
    results = results.drop_duplicates(subset=["match_id"]).sort_values(["date", "match_id"])
    results.to_csv(RESULTS_CSV, index=False)
    return results


def update(days: int, delay: float) -> None:
    """Completeaza zilele lipsa din ultimele `days` zile (fara azi si ieri,
    care pot fi incomplete) si suprafetele turneelor noi."""
    DATA_DIR.mkdir(exist_ok=True)
    results = load_results()
    have = set(zip(results["date"].astype(str), results["tour_type"].astype(str))) if not results.empty else set()
    surfaces = load_surfaces()

    end = dt.date.today() - dt.timedelta(days=2)
    new_rows: list[dict] = []
    for offset in range(days):
        day = end - dt.timedelta(days=offset)
        for tour_type in TOUR_TYPES:
            if (day.isoformat(), tour_type) in have:
                continue
            html = _get(RESULTS_URL, {"type": tour_type, "year": day.year, "month": f"{day.month:02d}", "day": f"{day.day:02d}"})
            time.sleep(delay)
            if html is None:
                continue
            day_matches = parse_results_page(html, day, tour_type)
            new_rows += [asdict(m) for m in day_matches]
            logger.info("%s %s: %d meciuri", day, tour_type, len(day_matches))
        if new_rows and offset % 20 == 19:
            results = _save(results, new_rows)  # salvare pe parcurs, in caz ca rularea e oprita
            new_rows = []

    if new_rows:
        results = _save(results, new_rows)

    missing = sorted(set(results["tournament_slug"].dropna()) - set(surfaces))
    logger.info("%d turnee fara suprafata in cache", len(missing))
    for slug in missing:
        html = _get(te.BASE_URL + slug)
        time.sleep(delay)
        surfaces[slug] = parse_tournament_surface(html) if html else ""
    pd.DataFrame(sorted(surfaces.items()), columns=["tournament_slug", "surface"]).to_csv(SURFACES_CSV, index=False)
    logger.info("Istoric: %d meciuri, %d turnee", len(results), len(surfaces))


def main() -> None:
    parser = argparse.ArgumentParser(description="Actualizeaza istoricul de rezultate pentru Elo.")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    update(args.days, args.delay)


if __name__ == "__main__":
    main()
