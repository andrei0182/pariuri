"""Script de verificare unica (2026-09-22): confirma, cu date reale de pe
TennisExplorer, daca meciul Gabriele Pennaforti vs Nicholas David Ionel
(ITF M, St. Margherita di P., te_match_id=3328741 din stats/picks_log.csv)
a fost afectat de bug-ul de ordine inversata (player1/player2) corectat in
find_scheduled_match(). Ruleaza doar din CI (GitHub Actions are acces la
tennisexplorer.com; mediul local de dezvoltare nu, proxy-ul blocheaza
domeniul). Nu scrie nimic, doar printeaza."""
from __future__ import annotations

import datetime as dt
import sys

sys.path.insert(0, ".")

from tenis_scraper import tennisexplorer as te  # noqa: E402

SB_PLAYER1 = "Gabriele Pennaforti"
SB_PLAYER2 = "Nicholas David Ionel"
KNOWN_MATCH_ID = 3328741
DATE = dt.date(2026, 9, 22)


def main() -> None:
    print(f"=== Verificare directa: match_id={KNOWN_MATCH_ID} ===")
    detail = te.fetch_and_parse_match(KNOWN_MATCH_ID)
    if detail is None:
        print("FETCH ESUAT pentru match_id direct.")
    else:
        print(f"detail.player1 = {detail.player1}")
        print(f"detail.player2 = {detail.player2}")
        print(f"surface_balance = {detail.surface_balance}")

    print()
    print("=== Verificare prin pipeline-ul normal: schedule + find_scheduled_match ===")
    for te_type in ("atp-single", "wta-single"):
        for day_offset in (0, 1):
            d = DATE + dt.timedelta(days=day_offset)
            schedule = te.fetch_daily_schedule(te_type, d)
            print(f"te_type={te_type} date={d}: {len(schedule)} meciuri gasite")
            match = next((m for m in schedule if m.match_id == KNOWN_MATCH_ID), None)
            if match is not None:
                print(f"  -> gasit direct dupa match_id: {match}")
            result = te.find_scheduled_match(SB_PLAYER1, SB_PLAYER2, schedule)
            if result is not None:
                scheduled, swapped = result
                print(f"  -> find_scheduled_match: scheduled={scheduled}")
                print(f"  -> SWAPPED = {swapped}")
                if swapped:
                    print(
                        "  -> CONFIRMAT: TennisExplorer lista jucatorii in ordine "
                        "inversa fata de Superbet pentru acest meci."
                    )
                else:
                    print(
                        "  -> Ordinea coincide (nu era swap) pentru acest meci - "
                        "cauza pierderii nu a fost acest bug specific pentru acest caz."
                    )


if __name__ == "__main__":
    main()
