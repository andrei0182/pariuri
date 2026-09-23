"""Outsideri mari (cota >= 4) si pariul "Peste X game-uri" pe ei - URMARIRE
PE HARTIE, fara bani, pana confirmam cu cotele reale Superbet.

De ce: in istoricul din data/results.csv.gz (62.101 meciuri, mar-sep 2026),
un outsider la cota >= 4 castiga >= 4 game-uri in 76% din meciuri. Cu un
filtru pe istoricul lui (analiza din 2026-09-23, doar meciuri de DINAINTE):
- cota outsiderului 4-7, nu ITF
- >= 5 infrangeri in istoric, in >= 85% din ele a facut >= 4 game-uri
rata urca la 90% (>= 4 game-uri) si 81% (>= 5), stabil in ambele perioade
testate (mar-iul 90.4% / 83.4%, aug-sep 89.5% / 79.8%, 1397 de meciuri).

Ce NU stim inca: cota Superbet pe aceste linii. Daca pentru "Peste 3.5" casa
da 1.10, nu exista castig. De aceea fiecare outsider e logat zilnic in
stats/underdog_games_log.csv cu linia si cota reala, iar check_results.py
completeaza rezultatul - dupa cateva saptamani vedem profitul real."""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

import history

LOG_PATH = Path("stats") / "underdog_games_log.csv"
LOG_COLUMNS = [
    "date", "tournament", "player1", "player2", "recommended_player", "opponent",
    "dog_odds", "level", "games_line", "games_odds", "est_rate", "break_even", "expected_value",
    "player_losses", "player_share", "filter_pass",
    "te_match_id", "result", "score", "checked_at", "set_scores", "rec_games", "games_result",
]

MIN_UNDERDOG_ODDS = 4.0
FILTER_MAX_ODDS = 7.0
MIN_PRIOR_LOSSES = 5
MIN_RESISTANCE = 0.85
MAX_LINE = 5.5  # liniile mai mari au rate istorice prea mici la outsideri de cota >= 4

LEVEL_BY_TOUR = {
    "atp": "ATP/WTA", "wta": "ATP/WTA",
    "challenger": "Challenger/125", "wta-125": "Challenger/125",
    "itf-m": "ITF", "itf-f": "ITF", "utr-m": "ITF", "utr-f": "ITF",
}


def history_level(tournament: str) -> str:
    """Nivelul unui turneu din istoric, dupa numele TennisExplorer."""
    t = str(tournament).lower()
    if "itf" in t or "utr" in t:
        return "ITF"
    if "challenger" in t or "125" in t:
        return "Challenger/125"
    return "ATP/WTA"


def odds_bucket(odds: float) -> str:
    return "4-5" if odds < 5 else ("5-7" if odds < 7 else "7+")


@dataclass
class UnderdogHistory:
    """samples: un rand per meci istoric cu outsider la cota >= 4, cu ce se
    stia despre el INAINTE de meci. loss_games: game-urile facute de fiecare
    jucator in infrangerile lui (pentru predictiile de azi)."""
    samples: pd.DataFrame
    loss_games: dict[str, list[int]]


def _sets(score: str) -> list[tuple[int, int]]:
    return [tuple(map(int, s.split("-"))) for s in str(score).split()]


def build_history(results: pd.DataFrame | None = None) -> UnderdogHistory:
    results = history.load_results() if results is None else results
    results = results.sort_values(["date", "match_id"])
    loss_games: dict[str, list[int]] = defaultdict(list)
    rows = []
    for m in results.itertuples(index=False):
        sets = _sets(m.score)
        games_w, games_l = sum(a for a, _ in sets), sum(b for _, b in sets)
        has_odds = pd.notna(m.odds_winner) and pd.notna(m.odds_loser) and m.odds_winner > 1 and m.odds_loser > 1
        if has_odds and len(sets) <= 3:
            fav_won = m.odds_winner < m.odds_loser
            dog = m.loser_slug if fav_won else m.winner_slug
            dog_odds = m.odds_loser if fav_won else m.odds_winner
            if dog_odds >= MIN_UNDERDOG_ODDS:
                prior = loss_games[dog]
                rows.append({
                    "level": history_level(m.tournament),
                    "dog_odds": dog_odds,
                    "dog_games": games_l if fav_won else games_w,
                    "player_losses": len(prior),
                    "player_share4": sum(g >= 4 for g in prior) / len(prior) if prior else math.nan,
                })
        loss_games[m.loser_slug].append(games_l)
    samples = pd.DataFrame(rows, columns=["level", "dog_odds", "dog_games", "player_losses", "player_share4"])
    samples["bucket"] = samples["dog_odds"].map(odds_bucket)
    samples["filter_pass"] = [
        passes_filter(r.level, r.dog_odds, r.player_losses, r.player_share4) for r in samples.itertuples()
    ]
    return UnderdogHistory(samples, dict(loss_games))


def passes_filter(level: str, dog_odds: float, player_losses: int, player_share4: float) -> bool:
    return (
        MIN_UNDERDOG_ODDS <= dog_odds < FILTER_MAX_ODDS
        and level != "ITF"
        and player_losses >= MIN_PRIOR_LOSSES
        and not math.isnan(player_share4)
        and player_share4 >= MIN_RESISTANCE
    )


def estimated_rate(hist: UnderdogHistory, level: str, dog_odds: float, line: float, filter_pass: bool) -> tuple[float, int]:
    """Cat de des a trecut linia un outsider comparabil, in istoric: grupul
    filtrului combinat daca meciul trece de filtru, altfel acelasi nivel si
    aceeasi grupa de cota."""
    s = hist.samples
    if s.empty:
        return math.nan, 0
    if filter_pass:
        group = s[s["filter_pass"]]
    else:
        group = s[(s["level"] == level) & (s["bucket"] == odds_bucket(dog_odds))]
    if group.empty:
        return math.nan, 0
    return float((group.dog_games > line).mean()), len(group)


def parse_games_lines(text: str) -> list[tuple[float, float]]:
    """"3.5@1.25; 4.5@1.45" -> [(3.5, 1.25), (4.5, 1.45)]."""
    out = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)@(\d+(?:\.\d+)?)", str(text or "")):
        out.append((float(m.group(1)), float(m.group(2))))
    return out


def select_underdogs(report: pd.DataFrame, hist: UnderdogHistory, labels: dict[str, str]) -> pd.DataFrame:
    """Un rand per (outsider, linie de game-uri <= MAX_LINE) din raportul zilei.
    `labels` = main._COLUMN_LABELS (raportul Excel are etichetele ca antet)."""
    col = lambda key: labels.get(key, key)  # noqa: E731
    rows = []
    for _, r in report.iterrows():
        odds1, odds2 = r.get(col("odds_1")), r.get(col("odds_2"))
        if pd.isna(odds1) or pd.isna(odds2):
            continue
        if odds1 >= MIN_UNDERDOG_ODDS and odds1 > odds2:
            side = 1
        elif odds2 >= MIN_UNDERDOG_ODDS and odds2 > odds1:
            side = 2
        else:
            continue
        dog, opp = (r.get(col("player1")), r.get(col("player2"))) if side == 1 else (r.get(col("player2")), r.get(col("player1")))
        dog_odds = float(odds1 if side == 1 else odds2)
        slug = r.get(col(f"p{side}_slug"))
        level = LEVEL_BY_TOUR.get(str(r.get(col("tour"))), "ITF")
        prior = hist.loss_games.get(slug, []) if isinstance(slug, str) and slug else []
        share4 = sum(g >= 4 for g in prior) / len(prior) if prior else math.nan
        ok = passes_filter(level, dog_odds, len(prior), share4)
        for line, games_odds in parse_games_lines(r.get(col(f"p{side}_games_lines"))):
            if line > MAX_LINE:
                continue
            rate, _ = estimated_rate(hist, level, dog_odds, line, ok)
            rows.append({
                "tournament": r.get(col("tournament"), ""),
                "player1": r.get(col("player1")), "player2": r.get(col("player2")),
                "recommended_player": dog, "opponent": opp,
                "dog_odds": dog_odds, "level": level,
                "games_line": line, "games_odds": games_odds,
                "est_rate": round(rate, 3) if not math.isnan(rate) else None,
                "break_even": round(1 / games_odds, 3),
                "expected_value": round(rate * games_odds - 1, 3) if not math.isnan(rate) else None,
                "player_losses": len(prior),
                "player_share": round(share4, 3) if not math.isnan(share4) else None,
                "filter_pass": ok,
                "te_match_id": r.get(col("te_match_id")),
            })
    return pd.DataFrame(rows)


def log_underdogs(candidates: pd.DataFrame, date_str: str) -> None:
    """Adauga in stats/underdog_games_log.csv (result/games_result = "pending",
    completate de check_results.py). Nu dubleaza la rulari repetate."""
    if candidates.empty:
        return
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log = pd.read_csv(LOG_PATH, dtype=str) if LOG_PATH.exists() else pd.DataFrame(columns=LOG_COLUMNS)
    new = candidates.copy()
    new["date"] = date_str
    new["result"] = "pending"
    for c in ("score", "checked_at", "set_scores", "rec_games", "games_result"):
        new[c] = ""
    new = new.astype(str)
    key = ["date", "recommended_player", "games_line"]
    if not log.empty:
        seen = set(map(tuple, log[key].astype(str).values))
        new = new[[tuple(v) not in seen for v in new[key].values]]
    log = pd.concat([log, new[LOG_COLUMNS]], ignore_index=True)
    log.to_csv(LOG_PATH, index=False)


def email_section_html(candidates: pd.DataFrame) -> str:
    """Doar outsiderii care trec de filtru, cea mai buna linie (EV maxim) per jucator."""
    head = ("<h3 style='margin-top:24px;'>Outsideri — game-uri (URMĂRIRE PE HÂRTIE, fără bani)</h3>"
            "<p style='color:#555;'>Outsider la cota 4–7 (nu ITF), cu &ge;5 înfrângeri în istoric, "
            "în &ge;85% din ele a făcut &ge;4 game-uri. Istoric: 90% au făcut &ge;4 game-uri, 81% &ge;5. "
            "Coloana EV = cât ar câștiga în medie un pariu de 1 unitate, dacă rata istorică se menține.</p>")
    if candidates.empty or not candidates["filter_pass"].any():
        return head + "<p><i>Niciun outsider azi nu trece de filtru.</i></p>"
    best = (candidates[candidates["filter_pass"]]
            .sort_values("expected_value", ascending=False)
            .drop_duplicates(subset=["recommended_player"]))
    items = []
    for _, c in best.iterrows():
        items.append(
            f"<li><b>{c.recommended_player}</b> (cota {c.dog_odds}) vs {c.opponent} — {c.tournament}: "
            f"Peste {c.games_line} game-uri @ {c.games_odds} | istoric {c.est_rate:.0%} vs prag {c.break_even:.0%} "
            f"| EV {c.expected_value:+.0%} | {c.player_losses} înfrângeri, {c.player_share:.0%} cu &ge;4 game-uri</li>"
        )
    return head + "<ul>" + "".join(items) + "</ul>"
