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
from datetime import timedelta
from pathlib import Path

import pandas as pd

import underdog
from tenis_scraper import tennisexplorer

LOG_PATH = Path("stats") / "picks_log.csv"
LOG_COLUMNS = [
    "date", "tournament", "player1", "player2", "recommended_player", "opponent",
    "edge_pp", "rec_odds", "comp_pct", "games_line", "games_odds",
    "te_match_id", "result", "score", "checked_at",
    "set_scores", "rec_games", "games_result",
]

# Cate zile inapoi mai incercam sa completam games_result pentru pick-uri deja
# rezolvate (won/lost) dar fara scor pe seturi - ex. cele logate inainte sa
# existe coloana, sau cand parse_set_scores n-a gasit nimic. Dupa atat, le
# lasam goale ca sa nu re-fetch-uim la nesfarsit pagini pe care nu le putem citi.
GAMES_BACKFILL_DAYS = 14


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


def load_log(path: Path = LOG_PATH, columns: list[str] = LOG_COLUMNS) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns)
    return pd.read_csv(path, dtype=str)


def save_log(df: pd.DataFrame, path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def _te_match_id(row: pd.Series) -> int | None:
    te_match_id = row.get("te_match_id")
    if pd.isna(te_match_id) or not str(te_match_id).strip():
        return None
    try:
        return int(float(te_match_id))
    except ValueError:
        return None


def _recommended_side(row: pd.Series, detail: tennisexplorer.MatchDetailData) -> int | None:
    """1 sau 2 - pe ce parte a paginii match-detail e jucatorul recomandat.
    None daca nu putem spune (nume formatat foarte diferit) - nu ghicim."""
    recommended = row.get("recommended_player", "")
    if names_overlap(recommended, detail.player1.name):
        return 1
    if names_overlap(recommended, detail.player2.name):
        return 2
    return None


def resolve_pick(row: pd.Series, detail: tennisexplorer.MatchDetailData) -> tuple[str, str]:
    """Cauta rezultatul unei recomandari in lista de meciuri recente ale
    jucatorului recomandat de pe pagina match-detail (acelasi te_match_id
    salvat la momentul recomandarii), dupa o intrare al carei adversar se
    potriveste cu cel salvat. Returneaza ("pending", "") daca nu gasim inca
    nimic (meci nejucat, sau lista inca neactualizata pe TennisExplorer)."""
    side = _recommended_side(row, detail)
    if side is None:
        return "pending", ""
    candidate_matches = detail.player1_recent if side == 1 else detail.player2_recent

    opponent = row.get("opponent", "")
    for m in candidate_matches:
        if names_overlap(opponent, m.opponent) and m.won is not None:
            return ("won" if m.won else "lost"), m.score

    return "pending", ""


def resolve_games(row: pd.Series, detail: tennisexplorer.MatchDetailData) -> tuple[str, str, str]:
    """Rezultatul pariului "Peste {games_line} game-uri" pe jucatorul
    recomandat (linia e per jucator, NU total meci - vezi
    _COL_GAMES_LINE_P1 din send_report_email.py). Numara game-urile
    castigate de el din scorul pe seturi al meciului.
    Returneaza (games_result, rec_games, set_scores) - toate "" daca nu
    avem scorul pe seturi sau linia. games_result e "void" la abandon/
    walkover (casele anuleaza de obicei piata de game-uri in cazul asta)."""
    if not detail.set_scores:
        return "", "", ""
    side = _recommended_side(row, detail)
    if side is None:
        return "", "", ""

    set_scores = " ".join(f"{a}-{b}" if side == 1 else f"{b}-{a}" for a, b in detail.set_scores)
    rec_games = sum(a if side == 1 else b for a, b in detail.set_scores)

    if detail.retired:
        return "void", str(rec_games), set_scores
    try:
        line = float(row.get("games_line"))
    except (TypeError, ValueError):
        return "", str(rec_games), set_scores
    if pd.isna(line):
        return "", str(rec_games), set_scores
    return ("won" if rec_games > line else "lost"), str(rec_games), set_scores


def _profit_units(rows: pd.DataFrame, result_col: str, odds_col: str) -> float:
    """Profit la miza fixa de 1 unitate: +(cota-1) la castig, -1 la pierdere."""
    odds = pd.to_numeric(rows[odds_col], errors="coerce")
    won = rows[result_col] == "won"
    return float((odds - 1).where(won, -1).sum())


def print_summary(log: pd.DataFrame) -> None:
    resolved = log[log["result"].isin(["won", "lost"])]
    if not resolved.empty and "rec_odds" in log.columns:
        win_rate = (resolved["result"] == "won").mean()
        profit = _profit_units(resolved, "result", "rec_odds")
        print(
            f"\nCastigator meci: {len(resolved)} recomandari confirmate, {win_rate:.0%} castigate, "
            f"profit {profit:+.2f} unitati (miza 1)."
        )
    games = log[log["games_result"].isin(["won", "lost"])]
    if "filter_pass" in log.columns:  # log-ul de outsideri: doar ce trece de filtru
        games = games[games["filter_pass"].astype(str) == "True"]
    if not games.empty:
        win_rate = (games["games_result"] == "won").mean()
        profit = _profit_units(games, "games_result", "games_odds")
        print(
            f"Peste game-uri jucator: {len(games)} confirmate, {win_rate:.0%} castigate, "
            f"profit {profit:+.2f} unitati (miza 1)."
        )


def main() -> None:
    for path, columns in ((LOG_PATH, LOG_COLUMNS), (underdog.LOG_PATH, underdog.LOG_COLUMNS)):
        print(f"\n== {path} ==")
        check_log(path, columns)


def check_log(path: Path, columns: list[str]) -> None:
    log = load_log(path, columns)
    if log.empty:
        print(f"Niciun rand in {path} inca -- nimic de verificat.")
        return
    for col in columns:
        if col not in log.columns:
            log[col] = ""
    log = log[columns + [c for c in log.columns if c not in columns]]

    today = Date.today()
    today_str = today.isoformat()
    backfill_from = (today - timedelta(days=GAMES_BACKFILL_DAYS)).isoformat()
    games_missing = log["games_result"].isna() | (log["games_result"] == "")

    is_pending = (log["result"] == "pending") & (log["date"] < today_str)
    needs_games = log["result"].isin(["won", "lost"]) & games_missing & (log["date"] >= backfill_from)
    to_check = log[is_pending | needs_games]
    if to_check.empty:
        print("Nimic 'pending' din zile anterioare si nimic de completat la game-uri.")
        print_summary(log)
        return

    print(f"Verific {len(to_check)} pick-uri (pending sau fara rezultat la game-uri)...")
    for idx in to_check.index:
        row = log.loc[idx]
        p1, p2 = row["player1"], row["player2"]
        rec = row["recommended_player"]

        match_id = _te_match_id(row)
        if match_id is None:
            if row["result"] == "pending":
                log.loc[idx, "result"] = "no_data"
                log.loc[idx, "checked_at"] = today_str
            continue
        detail = tennisexplorer.fetch_and_parse_match(match_id)
        if detail is None:
            continue

        if row["result"] == "pending":
            result, score = resolve_pick(row, detail)
            if result == "pending":
                continue
            log.loc[idx, "result"] = result
            log.loc[idx, "score"] = score
            log.loc[idx, "checked_at"] = today_str
            print(f"  {p1} vs {p2} -> {rec}: {result} ({score})")

        games_result, rec_games, set_scores = resolve_games(log.loc[idx], detail)
        if games_result:
            log.loc[idx, "games_result"] = games_result
            log.loc[idx, "rec_games"] = rec_games
            log.loc[idx, "set_scores"] = set_scores
            print(
                f"  {p1} vs {p2} -> {rec} peste {row['games_line']} game-uri: "
                f"{games_result} ({rec_games} game-uri, {set_scores})"
            )

    save_log(log, path)
    print_summary(log)


if __name__ == "__main__":
    main()
