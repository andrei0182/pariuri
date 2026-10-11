"""Diagnostic pentru filtrul din send_report_email.py: arata cate meciuri
trec de FIECARE conditie, in ordine, ca sa vezi unde pica majoritatea -
turneu ITF/UTR, edge combinat, estimare combinata, cota, linia de game-uri.

Ruleaza dupa ce ai generat raportul:
    python diagnose_filter.py output/tenis.xlsx
"""
import argparse

import pandas as pd

from send_report_email import (
    EXCLUDED_TOURS, MAX_ODDS, MIN_BLEND_EDGE_PP, MIN_BLEND_PCT,
    _COL_COMP1, _COL_COMP2, _COL_GAMES_ODDS_P1, _COL_GAMES_ODDS_P2,
    _COL_IMPL1, _COL_IMPL2, _COL_ODDS1, _COL_ODDS2, _COL_P1, _COL_P2,
    _COL_RATING_CONF, _COL_TOUR,
    blended_pct, filter_recommended_picks,
)


def main():
    parser = argparse.ArgumentParser(description="Diagnostic filtru recomandari tenis")
    parser.add_argument("xlsx", help="Calea catre fisierul Excel generat de main.py")
    args = parser.parse_args()

    df = pd.read_excel(args.xlsx, sheet_name="Tenis")
    print(f"Total meciuri in raport: {len(df)}")
    has_games = df[_COL_GAMES_ODDS_P1].notna().sum() + df[_COL_GAMES_ODDS_P2].notna().sum()
    print(f"Jucatori cu o cota Peste game-uri gasita: {has_games}")
    if has_games == 0:
        print("  -> ATENTIE: market-ul de game-uri NU a fost gasit (lipseste --extended-odds?).")

    steps = ["nu ITF/UTR", f"edge combinat >= {MIN_BLEND_EDGE_PP:g}pp", f"estimare combinata >= {MIN_BLEND_PCT:g}%",
             f"cota <= {MAX_ODDS:g}", "linie game-uri exista"]
    counts = [0] * len(steps)
    for _, row in df.iterrows():
        tour_ok = str(row.get(_COL_TOUR, "")).strip().lower() not in EXCLUDED_TOURS
        conf = row.get(_COL_RATING_CONF)
        conf = 0.0 if pd.isna(conf) else float(conf)
        for comp, impl, odds, godds in (
            (row.get(_COL_COMP1), row.get(_COL_IMPL1), row.get(_COL_ODDS1), row.get(_COL_GAMES_ODDS_P1)),
            (row.get(_COL_COMP2), row.get(_COL_IMPL2), row.get(_COL_ODDS2), row.get(_COL_GAMES_ODDS_P2)),
        ):
            if pd.isna(comp) or pd.isna(impl) or pd.isna(odds):
                continue
            blend = blended_pct(comp, impl, conf)
            checks = [tour_ok, blend - impl >= MIN_BLEND_EDGE_PP, blend >= MIN_BLEND_PCT, odds <= MAX_ODDS, not pd.isna(godds)]
            for i in range(len(checks)):
                if not all(checks[: i + 1]):
                    break
                counts[i] += 1

    print("\nJucatori care trec de conditii (cumulat, in ordine):")
    for label, n in zip(steps, counts):
        print(f"  {label}: {n}")

    picks = filter_recommended_picks(df)
    print(f"\nRecomandari finale (filter_recommended_picks): {len(picks)}")
    for _, row in picks.iterrows():
        p1, p2 = row[_COL_P1], row[_COL_P2]
        rec = p1 if row["_recommended_player"] == 1 else p2
        print(f"  {p1} vs {p2} -> {rec} (cota {row['_rec_odds']}, combinat {row['_blend_pct']:.1f}% "
              f"(+{row['_blend_edge_pp']:.1f}pp), model {row['_comp_pct']:.1f}%, "
              f"Peste {row['_games_line']} game-uri @ {row['_games_odds']})")


if __name__ == "__main__":
    main()
