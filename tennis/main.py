"""Punct de intrare — leaga Superbet (cote) cu TennisExplorer (stats) si
exporta un raport Excel.

STATUS: prima versiune functionala (2026-09-15). Acopera doar ATP si WTA
(singure tur-uri confirmate pentru mapping-ul catre tipul de pagina
TennisExplorer — vezi TOUR_TYPE_MAP din tenis_scraper/tennisexplorer.py).
Potrivirea meci Superbet <-> meci TennisExplorer se face dupa nume de
familie (euristica, nu 100% garantata) — verifica manual primele rulari.

Ce NU e inclus inca in aceasta versiune:
- calcularea automata a raportului victorii/infrangeri din formă recentă
  (campul `won` din RecentMatch nu e populat — ordinea numelor in perechea
  "NumeA-NumeB" de pe TennisExplorer nu indica sigur cine a castigat)
- H2H real cand chiar exista istoric comun (structura tabelului pentru
  acel caz nu a fost inca vazuta/confirmata)
- accidentari (tabelul playerInjuries de pe pagina de jucator exista, dar
  nu e inca legat in acest flux — ar necesita un fetch suplimentar per
  jucator)
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import time

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from tenis_scraper import events, tennisexplorer, tournaments

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

SUPPORTED_TOURS = ("atp", "wta")


def _recent_summary(matches: list[tennisexplorer.RecentMatch], limit: int = 5) -> str:
    parts = []
    for m in matches[:limit]:
        mark = {"True": "V", "False": "I", "None": "?"}[str(m.won)]
        parts.append(f"[{mark}] {m.tournament} {m.round} ({m.date}): {m.opponent} {m.score}")
    return " | ".join(parts) if parts else ""


def _surface_summary(balance: dict[str, tuple[str, str]]) -> str:
    parts = [f"{surface}: {v1} vs {v2}" for surface, (v1, v2) in balance.items()]
    return " | ".join(parts) if parts else ""


def build_report(date: dt.date, tours: tuple[str, ...] = SUPPORTED_TOURS, te_delay: float = 1.0) -> pd.DataFrame:
    rows: list[dict] = []

    for tour in tours:
        tour_ids = tournaments.all_tennis_tournament_ids(tours=(tour,))
        logger.info("Tur %s: %d turnee gasite in mapping-ul Superbet", tour, len(tour_ids))
        if not tour_ids:
            continue

        raw_events = events.fetch_events_for_all_tournaments(tour_ids, date)
        sb_matches = [events.parse_event(e, tour=tour) for e in raw_events]
        # exclude dublu / meciuri fara cote (cel mai probabil deja jucate/anulate)
        sb_matches = [m for m in sb_matches if m.odds_winner.player1 and m.odds_winner.player2]
        # excludem dublu - "/" in nume produce potriviri false la matching-ul dupa nume de familie
        sb_matches = [m for m in sb_matches if "/" not in m.player1 and "/" not in m.player2]
        logger.info("Tur %s: %d meciuri simplu Superbet cu cote gasite pentru %s", tour, len(sb_matches), date)

        te_type = tennisexplorer.TOUR_TYPE_MAP.get(tour)
        if te_type is None:
            logger.warning("Tur %s: nu are mapping catre TennisExplorer, sarim peste stats", tour)
            schedule = []
        else:
            # CONFIRMAT (2026-09-16): meciurile Superbet din ultimele ore UTC
            # ale zilei (ex. 23:00) pot cadea deja pe "ziua urmatoare" in
            # calendarul local (CET/CEST) al TennisExplorer - luam si ziua+1
            # ca sa nu pierdem acele meciuri. Nu am vazut nevoie de ziua-1
            # (orele foarte devreme UTC raman pe aceeasi zi locala TE, fiind
            # inaintea UTC, nu in urma).
            schedule = tennisexplorer.fetch_daily_schedule(te_type, date)
            schedule += tennisexplorer.fetch_daily_schedule(te_type, date + dt.timedelta(days=1))
            schedule = [m for m in schedule if "/" not in m.player1 and "/" not in m.player2]
            logger.info("Tur %s: %d meciuri simplu gasite in programul TennisExplorer (ziua + ziua urmatoare)", tour, len(schedule))

        for sb_match in sb_matches:
            row = {
                "tour": tour,
                "tournament": sb_match.tournament or "",
                "time": sb_match.time_text,
                "player1": sb_match.player1,
                "player2": sb_match.player2,
                "odds_1": sb_match.odds_winner.player1,
                "odds_2": sb_match.odds_winner.player2,
                "match_url": sb_match.match_url,
                "te_match_id": None,
                "p1_ranking": None,
                "p2_ranking": None,
                "surface_comparison": "",
                "p1_form_summary": "",
                "p2_form_summary": "",
                "p1_recent_form": "",
                "p2_recent_form": "",
                "h2h": "Neverificat",
            }

            scheduled = tennisexplorer.find_scheduled_match(sb_match.player1, sb_match.player2, schedule)
            if scheduled is not None and scheduled.match_id is not None:
                row["te_match_id"] = scheduled.match_id
                time.sleep(te_delay)  # nu bombarda serverul TennisExplorer
                detail = tennisexplorer.fetch_and_parse_match(scheduled.match_id)
                if detail is not None:
                    row["p1_ranking"] = detail.player1.ranking
                    row["p2_ranking"] = detail.player2.ranking
                    row["surface_comparison"] = _surface_summary(detail.surface_balance)
                    row["p1_form_summary"] = tennisexplorer.summarize_form(detail.player1_recent)
                    row["p2_form_summary"] = tennisexplorer.summarize_form(detail.player2_recent)
                    row["p1_recent_form"] = _recent_summary(detail.player1_recent)
                    row["p2_recent_form"] = _recent_summary(detail.player2_recent)
                    row["h2h"] = (
                        "Exista istoric H2H (detalii de verificat manual pe match_url)"
                        if detail.h2h_exists else "Fara istoric H2H"
                    )
            else:
                logger.info("Nu am gasit potrivire TennisExplorer pentru: %s vs %s", sb_match.player1, sb_match.player2)

            rows.append(row)

    return pd.DataFrame(rows)


_COLUMN_LABELS = {
    "tour": "Tur", "tournament": "Turneu", "time": "Ora",
    "player1": "Jucător 1", "player2": "Jucător 2",
    "odds_1": "Cotă 1", "odds_2": "Cotă 2", "match_url": "Link Superbet",
    "te_match_id": "TennisExplorer match_id",
    "p1_ranking": "Rank J1", "p2_ranking": "Rank J2",
    "surface_comparison": "Comparație Suprafață",
    "p1_form_summary": "Formă J1 (V-I ultimele 5)",
    "p2_form_summary": "Formă J2 (V-I ultimele 5)",
    "p1_recent_form": "Formă recentă J1 (ultimele 5)",
    "p2_recent_form": "Formă recentă J2 (ultimele 5)",
    "h2h": "H2H",
}


def save_report(df: pd.DataFrame, path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Tenis", index=False, header=False, startrow=1)
        ws = writer.sheets["Tenis"]

        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
        for col_idx, col_key in enumerate(df.columns, start=1):
            label = _COLUMN_LABELS.get(col_key, col_key)
            cell = ws.cell(row=1, column=col_idx, value=label)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            letter = get_column_letter(col_idx)
            ws.column_dimensions[letter].width = 28
        ws.freeze_panes = "A2"


def main() -> None:
    parser = argparse.ArgumentParser(description="Analiză meciuri tenis Superbet + stats TennisExplorer")
    parser.add_argument("--date", type=str, default=None, help="Data (YYYY-MM-DD), implicit azi")
    parser.add_argument("--output", type=str, default="output/tenis.xlsx")
    parser.add_argument("--tours", type=str, default=",".join(SUPPORTED_TOURS), help="Tur-uri, separate prin virgula (ex. atp,wta)")
    parser.add_argument("--te-delay", type=float, default=1.0, help="Pauza (secunde) intre request-uri catre TennisExplorer")
    args = parser.parse_args()

    date = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    tours = tuple(t.strip() for t in args.tours.split(",") if t.strip())

    logger.info("Rulare pentru data %s, tur-uri %s -> %s", date, tours, args.output)
    df = build_report(date, tours=tours, te_delay=args.te_delay)
    logger.info("Total meciuri in raport: %d", len(df))

    save_report(df, args.output)
    logger.info("Salvat: %s", args.output)


if __name__ == "__main__":
    main()
