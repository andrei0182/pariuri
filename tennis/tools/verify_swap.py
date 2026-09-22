"""Script de verificare unica (2026-09-22): confirma, cu date reale de pe
TennisExplorer, daca meciul Gabriele Pennaforti vs Nicholas David Ionel
(ITF M, St. Margherita di P., te_match_id=3328741 din stats/picks_log.csv)
a fost afectat de bug-ul de ordine inversata (player1/player2) intre
Superbet si TennisExplorer, corectat pe branch-ul
claude/sortare-eroare-analiza-v3ddk1 in find_scheduled_match().

Ruleaza doar din CI (GitHub Actions are acces la tennisexplorer.com;
mediul local de dezvoltare nu, proxy-ul blocheaza domeniul). Nu scrie
nimic, doar printeaza. Nu depinde de semnatura curenta a
find_scheduled_match() (aici, pe main, ea inca intoarce doar
ScheduledMatch, nu tuple) - reimplementeaza local aceeasi logica de
potrivire ca sa functioneze indiferent de branch."""
from __future__ import annotations

import datetime as dt
import re
import sys

sys.path.insert(0, ".")

from tenis_scraper import tennisexplorer as te  # noqa: E402

SB_PLAYER1 = "Gabriele Pennaforti"
SB_PLAYER2 = "Nicholas David Ionel"
KNOWN_MATCH_ID = 3328741
DATE = dt.date(2026, 9, 22)


def _normalize(name: str) -> set[str]:
    name = name.strip().lower()
    name = re.sub(r"[.\-']", " ", name)
    return set(name.split())


def check_order(sb_p1: str, sb_p2: str, te_p1: str, te_p2: str) -> str:
    sb1, sb2 = _normalize(sb_p1), _normalize(sb_p2)
    te1, te2 = _normalize(te_p1), _normalize(te_p2)
    direct = bool((sb1 & te1) and (sb2 & te2))
    swapped = bool((sb1 & te2) and (sb2 & te1))
    if direct and not swapped:
        return "DIRECT (ordine identica)"
    if swapped and not direct:
        return "SWAPPED (ordine inversata)"
    if direct and swapped:
        return "AMBIGUU (ambele conditii adevarate)"
    return "NICIO POTRIVIRE"


def main() -> None:
    print(f"=== Verificare directa: match_id={KNOWN_MATCH_ID} ===")
    detail = te.fetch_and_parse_match(KNOWN_MATCH_ID)
    if detail is None:
        print("FETCH ESUAT pentru match_id direct.")
    else:
        print(f"detail.player1 = {detail.player1}")
        print(f"detail.player2 = {detail.player2}")
        print(f"surface_balance = {detail.surface_balance}")
        print(
            "Ordine fata de Superbet (P1=Pennaforti, P2=Ionel): "
            + check_order(SB_PLAYER1, SB_PLAYER2, detail.player1.name, detail.player2.name)
        )

    print()
    print("=== Verificare prin schedule zilnic (cum face main.py) ===")
    for te_type in ("atp-single", "wta-single"):
        for day_offset in (0, 1):
            d = DATE + dt.timedelta(days=day_offset)
            schedule = te.fetch_daily_schedule(te_type, d)
            print(f"te_type={te_type} date={d}: {len(schedule)} meciuri gasite")
            match = next((m for m in schedule if m.match_id == KNOWN_MATCH_ID), None)
            if match is not None:
                print(f"  -> gasit dupa match_id: player1={match.player1!r} player2={match.player2!r}")
                print(
                    "  -> Ordine fata de Superbet: "
                    + check_order(SB_PLAYER1, SB_PLAYER2, match.player1, match.player2)
                )
            else:
                name_match = next(
                    (
                        m for m in schedule
                        if check_order(SB_PLAYER1, SB_PLAYER2, m.player1, m.player2)
                        in ("DIRECT (ordine identica)", "SWAPPED (ordine inversata)")
                    ),
                    None,
                )
                if name_match is not None:
                    print(f"  -> gasit dupa nume (match_id diferit={name_match.match_id}): {name_match}")
                    print(
                        "  -> Ordine fata de Superbet: "
                        + check_order(SB_PLAYER1, SB_PLAYER2, name_match.player1, name_match.player2)
                    )
                else:
                    print("  -> niciun meci Pennaforti/Ionel gasit in acest schedule")


if __name__ == "__main__":
    main()
