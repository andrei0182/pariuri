"""Verifica recomandarile din stats/picks_log.csv care sunt inca "pending"
si completeaza ce s-a intamplat de fapt, re-interogand TennisExplorer.

Nu exista o pagina de "scor live" pe TennisExplorer pe care s-o folosim
direct. In schimb, refolosim exact mecanismul deja existent pentru "forma
recenta": pagina match-detail a perechii ne da din nou lista de meciuri
RECENTE ale fiecarui jucator (cu scor si victorie/infrangere deja deduse
de tennisexplorer._annotate_won) - dupa ce meciul nostru s-a jucat, el
apare in capul acelei liste, cu adversarul potrivit.

Ruleaza INAINTE de generarea raportului de azi (vezi workflow-ul), la fel
ca la proiectul SuperBet de fotbal (check_results.py de acolo, acelasi
tipar). Sigur de rulat de mai multe ori - rândurile deja rezolvate sunt
sarite, iar un meci negasit inca (nejucat, sau nepotrivit) ramane pur si
simplu "pending" pentru rularea urmatoare.
"""
from __future__ import annotations

import re
import sys
import unicodedata
from datetime import date as Date
from pathlib import Path

import pandas as pd

from tenis_scraper import tennisexplorer

LOG_PATH = Path("stats") / "picks_log.csv"
LOG_COLUMNS = [
    "date", "tournament", "player1", "player2", "recommended_player", "opponent",
    "edge_pp", "rec_odds", "comp_pct", "games_line", "games_odds",
    "te_match_id", "result", "score", "checked_at",
]


def normalize_name(name: str) -> str:
    """Acelasi tip de normalizare ca la proiectul de fotbal, dar adaptata
    pentru nume de persoane (nu echipe) - pastram doar tokeni-i, fara sa
    ne bazam pe nume de familie unic (pot fi comune)."""
    if not isinstance(name, str):
        return ""
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().strip()
    normalized = re.sub(r"[.\-']", " ", normalized)
    return " ".join(normalized.split())


def names_overlap(name_a: str, name_b: str) -> bool:
    """True daca cele doua nume normalizate au cel putin un token in comun
    (de obicei numele de familie) - heuristica, la fel ca restul
    matching-ului de nume din proiect (vezi _normalize_name_for_matching
    din tennisexplorer.py)."""
    tokens_a, tokens_b = set(normalize_name(name_a).split()), set(normalize_name(name_b).split())
    if not tokens_a or not tokens_b:
        return False
    return bool(tokens_a & tokens_b)


def load_log() -> pd.DataFrame:
    if not LOG_PATH.exists():
        return pd.DataFrame(columns=LOG_COLUMNS)
    return pd.read_csv(LOG_PATH, dtype=str)


def save_log(df: pd.DataFrame) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(LOG_PATH, index=False)


def resolve_pick(row: pd.Series) -> tuple[str, str]:
    """Incearca sa gaseasca rezultatul unei recomandari, re-fetch-uind
    pagina match-detail (acelasi te_match_id salvat la momentul
    recomandarii) si cautand in lista de meciuri recente ale jucatorului
    recomandat o intrare al carei adversar se potriveste cu cel salvat.
    Returneaza ("pending", "") daca nu gasim inca nimic (meci nejucat,
    sau lista inca neactualizata pe TennisExplorer)."""
    te_match_id = row.get("te_match_id")
    if pd.isna(te_match_id) or not str(te_match_id).strip():
        return "no_data", ""
    try:
        match_id_int = int(float(te_match_id))
    except ValueError:
        return "no_data", ""

    detail = tennisexplorer.fetch_and_parse_match(match_id_int)
    if detail is None:
        return "pending", ""

    recommended = row.get("recommended_player", "")
    opponent = row.get("opponent", "")

    if names_overlap(recommended, detail.player1.name):
        candidate_matches = detail.player1_recent
    elif names_overlap(recommended, detail.player2.name):
        candidate_matches = detail.player2_recent
    else:
        # Nu am putut spune care e jucatorul recomandat pe pagina refetch-uita
        # (posibil nume formatat foarte diferit) - lasam pending, nu ghicim.
        return "pending", ""

    for m in candidate_matches:
        if names_overlap(opponent, m.opponent) and m.won is not None:
            return ("won" if m.won else "lost"), m.score

    return "pending", ""


def main() -> None:
    log = load_log()
    if log.empty:
        print("Niciun pick in log inca (stats/picks_log.csv nu exista sau e gol) -- nimic de verificat.")
        return

    today_str = Date.today().isoformat()
    pending = log[(log["result"] == "pending") & (log["date"] < today_str)]
    if pending.empty:
        print("Niciun pick 'pending' din zile anterioare.")
        return

    print(f"Verific {len(pending)} pick-uri 'pending'...")
    for idx in pending.index:
        result, score = resolve_pick(log.loc[idx])
        if result == "pending":
            continue
        log.loc[idx, "result"] = result
        log.loc[idx, "score"] = score
        log.loc[idx, "checked_at"] = today_str
        p1, p2 = log.loc[idx, "player1"], log.loc[idx, "player2"]
        rec = log.loc[idx, "recommended_player"]
        print(f"  {p1} vs {p2} -> {rec}: {result} ({score})")

    save_log(log)

    resolved = log[log["result"].isin(["won", "lost"])]
    if not resolved.empty:
        win_rate = (resolved["result"] == "won").mean()
        print(f"\nStatistica reala pana acum: {len(resolved)} recomandari confirmate, {win_rate:.0%} castigate.")


if __name__ == "__main__":
    main()
