"""Punct de intrare — SCAFFOLD, nu funcțional încă.

Odată ce Phase 0 e completă (sport id confirmat, market de rezultat final
confirmat, structura TennisExplorer confirmată), acest fișier va:

1. Găsi turneele de tenis active de azi (tournaments.py)
2. Prelua meciurile + cotele Superbet (events.py)
3. Pentru fiecare jucător, prelua H2H/formă/suprafață de pe TennisExplorer
   (tennisexplorer.py)
4. Combina totul în TennisMatch și exporta în Excel (export.py)

Nu rula asta încă — completează Phase 0 din README.md primul.
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analiză meciuri tenis Superbet + stats TennisExplorer")
    parser.add_argument("--date", type=str, default=None, help="Data (YYYY-MM-DD), implicit azi")
    parser.add_argument("--output", type=str, default="output/tenis.xlsx")
    args = parser.parse_args()

    date = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    logger.info("Rulare pentru data %s -> %s", date, args.output)

    raise NotImplementedError(
        "Phase 0 neterminată — vezi README.md. Confirmă TENNIS_SPORT_ID în "
        "events.py și structura TennisExplorer în tennisexplorer.py înainte "
        "de a construi fluxul complet aici."
    )


if __name__ == "__main__":
    main()
