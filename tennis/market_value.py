"""Superbet vs media pietei - URMARIRE PE HARTIE.

Nu ghicim noi castigatorul. Cota medie de pe TennisExplorer (media mai
multor case, din programul zilei) e luata drept "pretul corect". Un pariu
e interesant doar cand Superbet plateste clar MAI MULT decat media:
    valoare = cota Superbet / cota medie - 1  >=  MIN_VALUE
Daca media e un estimator bun al sansei reale, pariurile astea au, pe
termen lung, randament pozitiv - singura metoda folosita constant de
pariorii profesionisti (value betting / line shopping).

Fiecare alegere se logheaza in stats/market_value_log.csv; check_results.py
completeaza rezultatul. Abia dupa cateva sute de pariuri stim daca merge."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

LOG_PATH = Path("stats") / "market_value_log.csv"
LOG_COLUMNS = [
    "date", "tournament", "tour", "player1", "player2", "recommended_player", "opponent",
    "rec_odds", "market_odds", "value_pct", "te_match_id",
    "result", "score", "checked_at", "set_scores", "rec_games", "games_result",
]
MIN_VALUE = 0.05          # Superbet cu >= 5% peste media pietei
MIN_ODDS, MAX_ODDS = 1.30, 3.50   # fara favoriti zdrobitori si fara outsideri extremi
MAX_VALUE = 0.40          # peste atat e aproape sigur o eroare de date (jucatori inversati, cota veche)

_P1, _P2 = "Jucător 1", "Jucător 2"
_ODDS = {1: "Cotă 1", 2: "Cotă 2"}
_MARKET = {1: "Cotă medie piață J1 (TennisExplorer)", 2: "Cotă medie piață J2 (TennisExplorer)"}
_TOUR, _TOURNAMENT, _TIME, _TE_ID = "Tur", "Turneu", "Ora", "TennisExplorer match_id"


def _ro_time(value) -> str:
    try:
        return pd.Timestamp(value).tz_localize("UTC").tz_convert("Europe/Bucharest").strftime("%H:%M")
    except (ValueError, TypeError):
        return ""


def find_value(df: pd.DataFrame) -> pd.DataFrame:
    """Un rand per jucator unde Superbet plateste cu >= MIN_VALUE peste
    media pietei, la cota intre MIN_ODDS si MAX_ODDS. Sortat dupa valoare."""
    rows = []
    for _, r in df.iterrows():
        for side in (1, 2):
            odds, market = r.get(_ODDS[side]), r.get(_MARKET[side])
            if pd.isna(odds) or pd.isna(market) or market <= 1:
                continue
            value = odds / market - 1
            if MIN_VALUE <= value <= MAX_VALUE and MIN_ODDS <= odds <= MAX_ODDS:
                names = {1: r.get(_P1), 2: r.get(_P2)}
                rows.append({
                    "tournament": r.get(_TOURNAMENT, ""), "tour": r.get(_TOUR, ""), "time": _ro_time(r.get(_TIME)),
                    "player1": names[1], "player2": names[2],
                    "recommended_player": names[side], "opponent": names[3 - side],
                    "rec_odds": float(odds), "market_odds": float(market),
                    "value_pct": round(100 * value, 1), "te_match_id": r.get(_TE_ID),
                })
    out = pd.DataFrame(rows)
    return out.sort_values("value_pct", ascending=False) if not out.empty else out


def log_value(picks: pd.DataFrame, date_str: str) -> None:
    if picks.empty:
        return
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log = pd.read_csv(LOG_PATH, dtype=str) if LOG_PATH.exists() else pd.DataFrame(columns=LOG_COLUMNS)
    new = picks.copy()
    new["date"] = date_str
    new["result"] = "pending"
    for c in ("score", "checked_at", "set_scores", "rec_games", "games_result"):
        new[c] = ""
    new = new[LOG_COLUMNS].astype(str).replace({"None": "", "nan": ""})
    if not log.empty:
        seen = set(zip(log["date"], log["recommended_player"]))
        new = new[[(d, p) not in seen for d, p in zip(new["date"], new["recommended_player"])]]
    pd.concat([log, new], ignore_index=True).to_csv(LOG_PATH, index=False)


def summary_html() -> str:
    if not LOG_PATH.exists():
        return ""
    log = pd.read_csv(LOG_PATH, dtype=str)
    done = log[log["result"].isin(["won", "lost"])]
    if done.empty:
        return ""
    won = done["result"] == "won"
    odds = pd.to_numeric(done["rec_odds"], errors="coerce")
    expected = (1 / pd.to_numeric(done["market_odds"], errors="coerce")).sum()
    profit = float((odds - 1).where(won, -1).sum())
    return (f"<p style='color:#555;'><b>Pana acum:</b> {won.sum()} din {len(done)} castigate "
            f"(media pietei astepta ~{expected:.1f}), profit {profit:+.2f}u la miza 1.</p>")


def email_section_html(picks: pd.DataFrame) -> str:
    head = ("<h3 style='margin-top:24px;'>Superbet vs media pietei (TEST PE HARTIE)</h3>"
            "<p style='color:#555;'>Nu ghicim castigatorul: luam cota medie a pietei (TennisExplorer, mai multe case) "
            f"ca pret corect si aratam doar unde Superbet plateste cu &ge; {MIN_VALUE:.0%} mai mult, "
            f"la cota {MIN_ODDS:.2f}&ndash;{MAX_ODDS:.2f}.</p>")
    if picks.empty:
        return head + "<p><i>Niciun pariu cu valoare azi.</i></p>" + summary_html()
    items = "".join(
        f"<li><b>{c.recommended_player}</b> @ {c.rec_odds} (media pietei {c.market_odds}, +{c.value_pct}%) "
        f"vs {c.opponent} ({c.tour}, ora {c.time})</li>" for _, c in picks.iterrows()
    )
    return head + f"<ul>{items}</ul>" + summary_html()
