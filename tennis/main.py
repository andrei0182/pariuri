"""Punct de intrare - leaga Superbet (cote) cu TennisExplorer (stats),
calculeaza o estimare compusa (rank + forma) si exporta un raport Excel.

Estimarea compusa NU e un model predictiv validat statistic - e o medie
simpla intre probabilitatea implicita din rank (1/rank normalizat intre
cei doi jucatori) si probabilitatea implicita din rata de victorii pe
formă recentă. E gandita ca punct de plecare pentru propria analiza, nu
ca raspuns final. Coloana "Semnal" arata doar unde estimarea noastra
difera semnificativ (>7 puncte procentuale) de ce implica cota Superbet -
asta poate insemna fie ca am gasit ceva ce piata a ratat, fie (mai
probabil, mai ales la inceput) ca semnalele noastre simple (doar rank +
formă, fara accidentari/oboseala/conditii) sunt incomplete.

Ce NU e inclus inca:
- accidentari (tabelul playerInjuries de pe pagina de jucator exista, dar
  nu e inca legat in acest flux)
- H2H real cand chiar exista istoric comun (doar "exista/nu exista",
  fara detalii - structura tabelului pentru cazul "exista" nu a fost
  inca vazuta/confirmata)
- Cupa Davis / Billie Jean King Cup / United Cup (competitii pe echipe,
  structura de pagina diferita pe TennisExplorer)
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

SUPPORTED_TOURS = ("atp", "wta", "challenger", "wta-125", "itf-m", "itf-f", "utr-m", "utr-f")


def _recent_summary(matches: list[tennisexplorer.RecentMatch], limit: int = 10) -> str:
    parts = []
    for m in matches[:limit]:
        mark = {"True": "V", "False": "I", "None": "?"}[str(m.won)]
        parts.append(f"[{mark}] {m.tournament} {m.round} ({m.date}): {m.opponent} {m.score}")
    return " | ".join(parts) if parts else ""


def _parse_rank(rank_str: str | None) -> int | None:
    """Rank-ul vine ca text de pe TennisExplorer, ex. "169.", "-." (fara
    clasament). Curatam punctul final si convertim la int, None daca nu
    exista clasament."""
    if not rank_str:
        return None
    s = rank_str.strip().rstrip(".")
    try:
        val = int(s)
        return val if val > 0 else None
    except ValueError:
        return None


UNRANKED_FALLBACK = 2000  # presupunere pentru jucatori fara clasament, doar pentru scor relativ


def _rank_probability(rank1: int | None, rank2: int | None) -> float | None:
    """Probabilitate relativa bazata DOAR pe clasament, normalizata intre
    cei doi jucatori. Foloseste 1/sqrt(rank) in loc de 1/rank brut - 1/rank
    da valori nerealist de extreme la diferente mari (ex. rank 5 vs 200 ar
    da ~97.6% cu 1/rank, quando in tenis chiar si un favorit clar pastreaza
    o sansa realista pentru underdog). Tot o aproximare bruta, dar mai
    temperata."""
    r1 = rank1 if rank1 is not None else UNRANKED_FALLBACK
    r2 = rank2 if rank2 is not None else UNRANKED_FALLBACK
    score1, score2 = 1.0 / (r1 ** 0.5), 1.0 / (r2 ** 0.5)
    total = score1 + score2
    return score1 / total if total > 0 else None


def _form_probability(w1: int, l1: int, w2: int, l2: int) -> float | None:
    """Probabilitate relativa bazata pe rata de victorii din formă recentă
    (nu neaparat impotriva acelorasi adversari) - semnal slab de volatilitate
    pe termen scurt, nu o statistica riguroasa."""
    t1, t2 = w1 + l1, w2 + l2
    if t1 == 0 or t2 == 0:
        return None
    rate1, rate2 = w1 / t1, w2 / t2
    total = rate1 + rate2
    if total == 0:
        return None
    return rate1 / total


def _implied_probability(odds1: float, odds2: float) -> float | None:
    """Probabilitate implicita din cotele Superbet, normalizata ca sa
    elimine marja casei (suma 1/cota1 + 1/cota2 e de obicei >1)."""
    if not odds1 or not odds2:
        return None
    inv1, inv2 = 1.0 / odds1, 1.0 / odds2
    total = inv1 + inv2
    return inv1 / total if total > 0 else None


def _composite_estimate(rank_p: float | None, form_p: float | None) -> float | None:
    """Media semnalelor disponibile (rank + formă). Daca lipseste unul,
    folosim doar celalalt. NU e un model predictiv validat, doar o
    combinare simpla a semnalelor pe care le avem - de tratat ca punct de
    plecare pentru propria ta analiza, nu ca raspuns final."""
    parts = [p for p in (rank_p, form_p) if p is not None]
    if not parts:
        return None
    return sum(parts) / len(parts)


def _signal_label(composite_p1: float | None, implied_p1: float | None, threshold: float = 0.07) -> str:
    if composite_p1 is None or implied_p1 is None:
        return "Date insuficiente"
    diff = composite_p1 - implied_p1
    if diff > threshold:
        return f"Posibil value pe J1 (+{diff*100:.0f}pp vs piata)"
    if diff < -threshold:
        return f"Posibil value pe J2 (+{-diff*100:.0f}pp vs piata)"
    return "Aliniat cu piata"


def _surface_summary(balance: dict[str, tuple[str, str]]) -> str:
    parts = [f"{surface}: {v1} vs {v2}" for surface, (v1, v2) in balance.items()]
    return " | ".join(parts) if parts else ""


def _fetch_schedule_cached(te_type: str, date: dt.date, cache: dict) -> list[tennisexplorer.ScheduledMatch]:
    """Mai multe tur-uri Superbet (ex. challenger, itf-m, utr-m) mapeaza pe
    acelasi te_type ("atp-single") - evitam fetch-uri repetate ale aceleiasi
    pagini in cadrul aceleiasi rulari."""
    if te_type not in cache:
        schedule = tennisexplorer.fetch_daily_schedule(te_type, date)
        schedule += tennisexplorer.fetch_daily_schedule(te_type, date + dt.timedelta(days=1))
        schedule = [m for m in schedule if "/" not in m.player1 and "/" not in m.player2]
        cache[te_type] = schedule
    return cache[te_type]


def build_report(date: dt.date, tours: tuple[str, ...] = SUPPORTED_TOURS, te_delay: float = 1.0) -> pd.DataFrame:
    rows: list[dict] = []
    schedule_cache: dict[str, list[tennisexplorer.ScheduledMatch]] = {}

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
            schedule = _fetch_schedule_cached(te_type, date, schedule_cache)
            logger.info("Tur %s: %d meciuri simplu gasite in programul TennisExplorer (te_type=%s, ziua + ziua urmatoare)", tour, len(schedule), te_type)

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
                "implied_prob_1": None,
                "implied_prob_2": None,
                "composite_prob_1": None,
                "composite_prob_2": None,
                "signal": "Date insuficiente",
                "p1_recent_form": "",
                "p2_recent_form": "",
                "h2h": "Neverificat",
            }

            implied_p1 = _implied_probability(sb_match.odds_winner.player1, sb_match.odds_winner.player2)
            if implied_p1 is not None:
                row["implied_prob_1"] = round(implied_p1 * 100, 1)
                row["implied_prob_2"] = round((1 - implied_p1) * 100, 1)

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

                    rank1, rank2 = _parse_rank(detail.player1.ranking), _parse_rank(detail.player2.ranking)
                    w1, l1 = tennisexplorer.form_win_loss(detail.player1_recent)
                    w2, l2 = tennisexplorer.form_win_loss(detail.player2_recent)

                    rank_p1 = _rank_probability(rank1, rank2)
                    form_p1 = _form_probability(w1, l1, w2, l2)
                    composite_p1 = _composite_estimate(rank_p1, form_p1)

                    if composite_p1 is not None:
                        row["composite_prob_1"] = round(composite_p1 * 100, 1)
                        row["composite_prob_2"] = round((1 - composite_p1) * 100, 1)
                        row["signal"] = _signal_label(composite_p1, implied_p1)
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
    "p1_form_summary": "Formă J1 (V-I, meciuri disponibile pe TennisExplorer)",
    "p2_form_summary": "Formă J2 (V-I, meciuri disponibile pe TennisExplorer)",
    "implied_prob_1": "% Implicit Cotă J1",
    "implied_prob_2": "% Implicit Cotă J2",
    "composite_prob_1": "% Estimare Compusă J1 (rank+formă)",
    "composite_prob_2": "% Estimare Compusă J2 (rank+formă)",
    "signal": "Semnal (estimare vs piață)",
    "p1_recent_form": "Formă recentă J1 (meciuri disponibile)",
    "p2_recent_form": "Formă recentă J2 (meciuri disponibile)",
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
