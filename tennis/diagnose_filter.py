"""Diagnostic pentru filtrul din send_report_email.py: arata cate meciuri
trec de FIECARE conditie separat, ca sa vezi exact unde pica majoritatea -
edge, cota, estimare proprie (>=60%), sau linia de 4.5 game-uri.

Ruleaza din radacina repo-ului, dupa ce ai generat raportul:
    python diagnose_filter.py stats/test_report.xlsx
"""
import sys
import pandas as pd
from send_report_email import (
    MIN_EDGE_PP, MIN_ODDS, MIN_COMPOSITE_PCT,
    _COL_P1, _COL_P2, _COL_ODDS1, _COL_ODDS2,
    _COL_COMP1, _COL_COMP2, _COL_IMPL1, _COL_IMPL2,
    _COL_RATING_CONF, _COL_GAMES45_P1, _COL_GAMES45_P2,
    filter_recommended_picks,
)


def main():
    if len(sys.argv) != 2:
        print("Foloseste: python diagnose_filter.py <cale_raport.xlsx>")
        sys.exit(1)

    df = pd.read_excel(sys.argv[1], sheet_name="Tenis")
    print(f"Total meciuri in raport: {len(df)}\n")

    has_games45 = df[_COL_GAMES45_P1].notna().sum() + df[_COL_GAMES45_P2].notna().sum()
    print(f"Randuri cu vreo cota Peste 4.5 game-uri gasita (J1 sau J2): {has_games45}")
    if has_games45 == 0:
        print("  -> ATENTIE: market-ul de game-uri NU a fost gasit deloc.")
        print("     Fie n-ai rulat --extended-odds, fie heuristica de nume")
        print("     (cauta 'total'+'game', fara 'set') nu se potriveste cu")
        print("     numele real al market-ului pe Superbet.\n")
    else:
        print("  -> Market-ul de game-uri A FOST gasit pe cel putin un meci.\n")

    # Numaram, pas cu pas, cate meciuri trec de fiecare conditie IN PARTE
    # (nu inlantuite), pentru fiecare parte (J1 si J2 separat)
    pass_edge = pass_odds = pass_comp = pass_games45 = 0
    pass_edge_and_odds = 0
    pass_edge_odds_comp = 0
    examples_missing_games45 = []

    for _, row in df.iterrows():
        comp1, comp2 = row.get(_COL_COMP1), row.get(_COL_COMP2)
        impl1, impl2 = row.get(_COL_IMPL1), row.get(_COL_IMPL2)
        odds1, odds2 = row.get(_COL_ODDS1), row.get(_COL_ODDS2)
        games1, games2 = row.get(_COL_GAMES45_P1), row.get(_COL_GAMES45_P2)
        conf = row.get(_COL_RATING_CONF)
        if pd.isna(comp1) or pd.isna(impl1):
            continue
        conf = 0.0 if pd.isna(conf) else float(conf)
        weight = 0.3 + 0.7 * conf
        edge1 = comp1 - impl1
        edge1_w = edge1 * weight

        for edge_w, odds, comp, games, label in (
            (edge1_w, odds1, comp1, games1, f"{row.get(_COL_P1)} (J1)"),
            (-edge1_w, odds2, comp2, games2, f"{row.get(_COL_P2)} (J2)"),
        ):
            if edge_w < MIN_EDGE_PP:
                continue
            pass_edge += 1
            if pd.isna(odds) or odds < MIN_ODDS:
                continue
            pass_odds += 1
            pass_edge_and_odds += 1
            if pd.isna(comp) or comp < MIN_COMPOSITE_PCT:
                continue
            pass_comp += 1
            pass_edge_odds_comp += 1
            if pd.isna(games):
                if len(examples_missing_games45) < 5:
                    examples_missing_games45.append(f"{label} - edge {edge_w:.0f}pp, cota {odds}, estimare {comp}%")
                continue
            pass_games45 += 1

    print(f"Treceau de edge >= {MIN_EDGE_PP:.0f}pp: {pass_edge}")
    print(f"Din care si cota >= {MIN_ODDS:.1f}: {pass_edge_and_odds}")
    print(f"Din care si estimare proprie >= {MIN_COMPOSITE_PCT:.0f}%: {pass_edge_odds_comp}")
    print(f"Din care si linia Peste 4.5 game-uri exista: {pass_games45}")

    if examples_missing_games45:
        print(f"\nExemple care treceau de primele 3 conditii dar PICA la linia de 4.5:")
        for ex in examples_missing_games45:
            print(f"  - {ex}")

    print("\n--- Rezultat final (toate 4 conditii, via filter_recommended_picks) ---")
    picks = filter_recommended_picks(df)
    print(f"Recomandari finale: {len(picks)}")
    for _, row in picks.iterrows():
        p1, p2 = row[_COL_P1], row[_COL_P2]
        rec = p1 if row["_recommended_player"] == 1 else p2
        print(f"  {p1} vs {p2} -> {rec} (edge {row['_edge_pp']:.0f}pp, cota {row['_rec_odds']}, "
              f"estimare {row['_comp_pct']:.1f}%, Peste 4.5 @ {row['_games45_odds']})")


if __name__ == "__main__":
    main()
