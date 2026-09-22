"""Script de diagnostic unic (2026-09-22): reface, cu date reale de pe
TennisExplorer, calculul estimarii compuse pentru un meci specific unde
recomandarea (Santiago Rodriguez Taverna, 58.2% sanse de castig conform
raportului) a iesit gresita in practica (Taverna a pierdut categoric,
3-6 1-6). Scopul e sa vedem daca datele brute (rank, forma recenta,
rating pe suprafata) folosite de main.py erau corecte pentru ACESTI doi
jucatori, sau daca a fost o problema de potrivire/date (nume gresit,
statistici stale etc). Ruleaza doar din CI (tennisexplorer.com e blocat
din mediul local de dezvoltare). Nu scrie nimic, doar printeaza."""
from __future__ import annotations

import datetime as dt
import sys

sys.path.insert(0, ".")

import main as tennis_main  # noqa: E402
from tenis_scraper import tennisexplorer as te  # noqa: E402

SB_PLAYER1 = "Santiago Rodriguez Taverna"
SB_PLAYER2 = "Pedro Boscardin Dias"
DATE = dt.date(2026, 9, 22)
# tur "challenger" e mapat la te_type "atp-single" (vezi TOUR_TYPE_MAP)
TE_TYPE = "atp-single"


def main() -> None:
    schedule: list[te.ScheduledMatch] = []
    for day_offset in (0, 1):
        d = DATE + dt.timedelta(days=day_offset)
        day_schedule = te.fetch_daily_schedule(TE_TYPE, d)
        print(f"te_type={TE_TYPE} date={d}: {len(day_schedule)} meciuri gasite")
        schedule.extend(day_schedule)

    result = te.find_scheduled_match(SB_PLAYER1, SB_PLAYER2, schedule)
    if result is None:
        print("NU S-A GASIT nicio potrivire TennisExplorer pentru acest meci.")
        return

    scheduled, swapped = result
    print(f"scheduled = {scheduled}")
    print(f"swapped = {swapped}")

    detail = te.fetch_and_parse_match(scheduled.match_id)
    if detail is None:
        print("FETCH ESUAT pentru match_id gasit.")
        return

    if swapped:
        detail.player1, detail.player2 = detail.player2, detail.player1
        detail.player1_recent, detail.player2_recent = detail.player2_recent, detail.player1_recent
        detail.surface_balance = {
            surface: (v2, v1) for surface, (v1, v2) in detail.surface_balance.items()
        }

    print()
    print(f"P1 (trebuie sa fie {SB_PLAYER1}): {detail.player1}")
    print(f"P2 (trebuie sa fie {SB_PLAYER2}): {detail.player2}")
    print(f"surface_balance = {detail.surface_balance}")
    print(f"h2h_exists = {detail.h2h_exists}")

    print()
    print("=== Forma recenta P1 ===")
    for m in detail.player1_recent:
        print(f"  {m}")
    print("=== Forma recenta P2 ===")
    for m in detail.player2_recent:
        print(f"  {m}")

    rank1 = tennis_main._parse_rank(detail.player1.ranking)
    rank2 = tennis_main._parse_rank(detail.player2.ranking)
    w1, l1 = te.form_win_loss(detail.player1_recent)
    w2, l2 = te.form_win_loss(detail.player2_recent)

    rank_p1 = tennis_main._rank_probability(rank1, rank2)
    form_p1 = tennis_main._form_probability(w1, l1, w2, l2)
    rating_p1, rating_confidence = tennis_main._career_rating_probability(detail.surface_balance)
    composite_p1 = tennis_main._composite_estimate(rank_p1, form_p1, rating_p1, rating_confidence)

    print()
    print(f"rank1={rank1} rank2={rank2} -> rank_p1={rank_p1}")
    print(f"forma P1: {w1}W/{l1}L, forma P2: {w2}W/{l2}L -> form_p1={form_p1}")
    print(f"rating_p1={rating_p1} rating_confidence={rating_confidence}")
    print(f"COMPOSITE_P1 (sanse castig {SB_PLAYER1}) = {composite_p1}")
    if composite_p1 is not None:
        print(f"  = {composite_p1 * 100:.1f}% (raportul de azi arata 58.2%)")


if __name__ == "__main__":
    main()
