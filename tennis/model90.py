"""Modelul "90%" - URMARIRE PE HARTIE.

Un model statistic (gradient boosting, scikit-learn) invata din istoric
(data/results.csv.gz) doar pe indicatori de jucator, calculati din meciurile
de DINAINTE: Elo general si pe suprafata, victorii si game-uri pe suprafata,
forma (5 si 10 meciuri), oboseala, meciuri directe, adversari comuni, cate
game-uri face cand pierde, nivelul turneului. Fara cote.

Doua piete:
- "castiga meciul" (TARGET_WIN)
- "adversarul face sub 6.5 game-uri" (TARGET_OPP_UNDER), adica victorie clara

Pragul de probabilitate se alege zilnic, cinstit: modelul se antreneaza fara
ultimele VALIDATION_DAYS zile, iar pragul e cel mai mic care da >= 90% pe
acele zile. Acelasi model si prag se aplica meciurilor de azi.

Test 2026-10-13 (antrenat pana pe 12 sept., testat pe 13 sept. - 11 oct.):
"castiga meciul" 90.9% (594 de pariuri, cota medie 1.17, profit ~+2%);
"adversarul sub 6.5 game-uri" 91.6% (95 de pariuri, cotele nu le stim inca)."""
from __future__ import annotations

import datetime as dt
import re
import warnings
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

import elo
import underdog

LOG_PATH = Path("stats") / "model90_log.csv"
LOG_COLUMNS = [
    "date", "tournament", "tour", "player1", "player2", "market", "recommended_player", "opponent",
    "probability", "threshold", "rec_odds", "games_bet", "games_line", "games_odds", "te_match_id",
    "result", "score", "checked_at", "set_scores", "rec_games", "games_result",
]
TARGET_WIN, TARGET_OPP_UNDER = "y_win", "y_opp_u65"
MARKETS = {TARGET_WIN: "castiga meciul", TARGET_OPP_UNDER: "adversarul sub 6.5 game-uri"}
OPP_UNDER_LINE = 6.5
TARGET_RATE = 0.90
VALIDATION_DAYS = 21
MIN_VALIDATION_PICKS = 30
TRAIN_FROM = "2026-05-01"   # primele saptamani de istoric doar "incalzesc" Elo / forma
LEVEL_CODE = {"ATP/WTA": 2, "Challenger/125": 1, "ITF": 0}
SURFACE_CODE = {"Hard": 0, "Clay": 1, "Grass": 2, "Indoors": 3}
FEATURES = [
    "elo", "elo_ov", "elo_sf", "n_x", "n_y", "ns_x", "ns_y", "swr_x", "swr_y", "gs_x", "gs_y", "awr_x", "awr_y",
    "f5_x", "f5_y", "f10_x", "f10_y", "load_x", "load_y", "res4_x", "res4_y", "h2h", "h2hn", "co", "con",
    "lvl_c", "sf_c", "swr_d", "gs_d", "awr_d", "f5_d", "f10_d", "load_d", "res4_d",
]

# Coloanele raportului Excel (main._COLUMN_LABELS)
_P1, _P2 = "Jucător 1", "Jucător 2"
_ODDS = {1: "Cotă 1", 2: "Cotă 2"}
_SLUG = {1: "TennisExplorer J1", 2: "TennisExplorer J2"}
_UNDER = {1: "Linii Game-uri J1 (linie@cotă Sub)", 2: "Linii Game-uri J2 (linie@cotă Sub)"}
_SURFACE, _TOUR, _TOURNAMENT, _TIME, _TE_ID = "Suprafață Meci", "Tur", "Turneu", "Ora", "TennisExplorer match_id"


def _rate(wl, k):
    return wl[0] / sum(wl) if sum(wl) >= k else np.nan


class State:
    """Tot ce se stie despre jucatori pana la un moment dat."""

    def __init__(self):
        self.book = elo.EloBook()
        self.swl = defaultdict(lambda: [0, 0])
        self.sg = defaultdict(lambda: [0, 0])
        self.awl = defaultdict(lambda: [0, 0])
        self.vs = defaultdict(lambda: defaultdict(lambda: [0, 0]))
        self.last = defaultdict(list)
        self.dates = defaultdict(list)
        self.loss_games = defaultdict(list)

    def features(self, x: str, y: str, surface: str, day: dt.date, level: str) -> dict:
        p = self.book.predict(x, y, surface)
        common = (set(self.vs[x]) & set(self.vs[y])) - {x, y}
        co = np.nan
        if len(common) >= 2:
            co = (np.mean([self.vs[x][c][0] / sum(self.vs[x][c]) for c in common])
                  - np.mean([self.vs[y][c][0] / sum(self.vs[y][c]) for c in common]))

        def gs(z):
            g = self.sg[(z, surface)]
            return g[0] / sum(g) if sum(g) >= 40 else np.nan

        def form(z, k):
            q = self.last[z][-k:]
            return float(np.mean(q)) if len(q) >= 5 else np.nan

        def load(z):
            return sum(1 for q in self.dates[z][-6:] if (day - q).days <= 3)

        def res4(z):
            q = self.loss_games[z]
            return float(np.mean([g >= 4 for g in q])) if len(q) >= 5 else np.nan

        f = {
            "elo": p["blend"], "elo_ov": p["overall"], "elo_sf": p["surface"],
            "n_x": self.book.n_overall[x], "n_y": self.book.n_overall[y],
            "ns_x": self.book.n_surface[(x, surface)], "ns_y": self.book.n_surface[(y, surface)],
            "swr_x": _rate(self.swl[(x, surface)], 5), "swr_y": _rate(self.swl[(y, surface)], 5),
            "gs_x": gs(x), "gs_y": gs(y), "awr_x": _rate(self.awl[x], 5), "awr_y": _rate(self.awl[y], 5),
            "f5_x": form(x, 5), "f5_y": form(y, 5), "f10_x": form(x, 10), "f10_y": form(y, 10),
            "load_x": load(x), "load_y": load(y), "res4_x": res4(x), "res4_y": res4(y),
            "h2h": self.vs[x][y][0] - self.vs[x][y][1], "h2hn": sum(self.vs[x][y]), "co": co, "con": len(common),
            "lvl_c": LEVEL_CODE.get(level, 0), "sf_c": SURFACE_CODE.get(surface, -1),
        }
        for a in ("swr", "gs", "awr", "f5", "f10", "load", "res4"):
            f[f"{a}_d"] = f[f"{a}_x"] - f[f"{a}_y"]
        return f

    def update(self, w: str, l: str, surface: str, sets: list[tuple[int, int]], day: dt.date) -> None:
        gw, gl = sum(a for a, _ in sets), sum(b for _, b in sets)
        self.book.update(w, l, surface)
        self.swl[(w, surface)][0] += 1
        self.swl[(l, surface)][1] += 1
        self.awl[w][0] += 1
        self.awl[l][1] += 1
        self.sg[(w, surface)][0] += gw
        self.sg[(w, surface)][1] += gl
        self.sg[(l, surface)][0] += gl
        self.sg[(l, surface)][1] += gw
        self.vs[w][l][0] += 1
        self.vs[l][w][1] += 1
        self.last[w].append(1)
        self.last[l].append(0)
        self.dates[w].append(day)
        self.dates[l].append(day)
        self.loss_games[l].append(gl)


def build(matches: pd.DataFrame | None = None) -> tuple[State, pd.DataFrame]:
    """Trece prin istoric in ordine cronologica. Intoarce starea finala si
    randurile de antrenare (cate unul per jucator per meci, cu indicatorii
    de DINAINTEA meciului si rezultatele)."""
    matches = elo.load_matches() if matches is None else matches
    state, rows = State(), []
    for r in matches.itertuples(index=False):
        sets = [tuple(map(int, x.split("-"))) for x in str(r.score).split()]
        day = dt.date.fromisoformat(r.date)
        if r.date >= TRAIN_FROM and len(sets) <= 3:
            level = underdog.history_level(r.tournament)
            for x, y, won in ((r.winner_slug, r.loser_slug, True), (r.loser_slug, r.winner_slug, False)):
                mine = [(a, b) if won else (b, a) for a, b in sets]
                row = state.features(x, y, r.surface, day, level)
                row.update(date=r.date, y_win=won, y_opp_u65=sum(b for _, b in mine) < OPP_UNDER_LINE)
                rows.append(row)
        state.update(r.winner_slug, r.loser_slug, r.surface, sets, day)
    return state, pd.DataFrame(rows)


@dataclass
class Model:
    estimator: object
    threshold: float | None
    validation_rate: float
    validation_picks: int
    empty_features: tuple = ()   # coloane fara nicio valoare la antrenare (inlocuite cu -1)

    def matrix(self, df: pd.DataFrame) -> pd.DataFrame:
        x = df[FEATURES].astype(float)
        if self.empty_features:
            x = x.assign(**{c: -1.0 for c in self.empty_features})
        return x

    def proba(self, df: pd.DataFrame) -> np.ndarray:
        return self.estimator.predict_proba(self.matrix(df))[:, 1]


def train(rows: pd.DataFrame, target: str) -> Model:
    """Antrenat fara ultimele VALIDATION_DAYS zile; pragul = cel mai mic care
    da >= TARGET_RATE pe ele (None daca nu se atinge)."""
    from sklearn.ensemble import HistGradientBoostingClassifier

    last = dt.date.fromisoformat(str(rows["date"].max()))
    cut = (last - dt.timedelta(days=VALIDATION_DAYS - 1)).isoformat()
    tr, va = rows[rows["date"] < cut], rows[rows["date"] >= cut]
    if tr[target].nunique() < 2 or va.empty:
        return Model(None, None, float("nan"), 0)
    est = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=31,
                                         l2_regularization=1.0, random_state=0)
    empty = tuple(c for c in FEATURES if tr[c].isna().all())
    model = Model(est, None, float("nan"), 0, empty)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        est.fit(model.matrix(tr), tr[target])
    p, y = model.proba(va), va[target].to_numpy()
    for t in np.arange(0.5, 0.995, 0.005):
        sel = p >= t
        if sel.sum() >= MIN_VALIDATION_PICKS and y[sel].mean() >= TARGET_RATE:
            model.threshold, model.validation_rate, model.validation_picks = round(float(t), 3), float(y[sel].mean()), int(sel.sum())
            break
    return model


def _line_odds(text, line: float):
    m = re.search(rf"(?:^|;\s*){re.escape(f'{line:g}')}@(\d+(?:\.\d+)?)", str(text or ""))
    return float(m.group(1)) if m else None


def _ro_time(value) -> str:
    try:
        return pd.Timestamp(value).tz_localize("UTC").tz_convert("Europe/Bucharest").strftime("%H:%M")
    except (ValueError, TypeError):
        return ""


def predict(df: pd.DataFrame, state: State, models: dict[str, Model], today: dt.date) -> pd.DataFrame:
    """Alegerile de azi: jucatorii la care probabilitatea modelului trece de prag."""
    rows = []
    for _, r in df.iterrows():
        slugs = {1: r.get(_SLUG[1]), 2: r.get(_SLUG[2])}
        if not all(isinstance(s, str) and s for s in slugs.values()):
            continue
        surface = r.get(_SURFACE)
        surface = surface.strip().capitalize() if isinstance(surface, str) else ""
        level = underdog.LEVEL_BY_TOUR.get(str(r.get(_TOUR, "")), "ITF")
        names = {1: r.get(_P1), 2: r.get(_P2)}
        for side in (1, 2):
            other = 3 - side
            feats = pd.DataFrame([state.features(slugs[side], slugs[other], surface, today, level)])
            for target, model in models.items():
                if model.threshold is None:
                    continue
                prob = float(model.proba(feats)[0])
                if prob < model.threshold:
                    continue
                odds = r.get(_ODDS[side])
                rows.append({
                    "tournament": r.get(_TOURNAMENT, ""), "tour": r.get(_TOUR, ""), "time": _ro_time(r.get(_TIME)),
                    "player1": names[1], "player2": names[2], "market": MARKETS[target],
                    "recommended_player": names[side], "opponent": names[other],
                    "probability": round(prob, 3), "threshold": model.threshold,
                    "rec_odds": float(odds) if pd.notna(odds) else None,
                    # "adversarul sub 6.5": cota Sub pe linia 6.5 a ADVERSARULUI; la "castiga
                    # meciul" urmarim si "peste 8.5 game-uri" pe jucatorul ales
                    "games_bet": "opp_under" if target == TARGET_OPP_UNDER else "over",
                    "games_line": OPP_UNDER_LINE if target == TARGET_OPP_UNDER else 8.5,
                    "games_odds": _line_odds(r.get(_UNDER[other]), OPP_UNDER_LINE) if target == TARGET_OPP_UNDER else None,
                    "te_match_id": r.get(_TE_ID),
                })
    out = pd.DataFrame(rows)
    return out.sort_values("probability", ascending=False) if not out.empty else out


def run_today(df: pd.DataFrame, today: dt.date) -> tuple[pd.DataFrame, dict[str, Model]]:
    state, rows = build()
    models = {t: train(rows, t) for t in MARKETS}
    return predict(df, state, models, today), models


def log_picks(picks: pd.DataFrame, date_str: str) -> None:
    """Rezultatul il completeaza check_results.py: "result" = a castigat
    meciul jucatorul ales; "games_result" = pariul pe game-uri (games_bet:
    "opp_under" = adversarul sub games_line, "over" = jucatorul peste)."""
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
        seen = set(zip(log["date"], log["market"], log["recommended_player"]))
        new = new[[k not in seen for k in zip(new["date"], new["market"], new["recommended_player"])]]
    pd.concat([log, new], ignore_index=True).to_csv(LOG_PATH, index=False)


def summary_html() -> str:
    if not LOG_PATH.exists():
        return ""
    log = pd.read_csv(LOG_PATH, dtype=str)
    parts = []
    win = log[(log["market"] == MARKETS[TARGET_WIN]) & log["result"].isin(["won", "lost"])]
    if not win.empty:
        won = win["result"] == "won"
        odds = pd.to_numeric(win["rec_odds"], errors="coerce")
        parts.append(f"castiga meciul: {won.sum()} din {len(win)} ({won.mean():.0%}), "
                     f"profit {float((odds - 1).where(won, -1).sum()):+.2f}u")
    opp = log[(log["market"] == MARKETS[TARGET_OPP_UNDER]) & log["games_result"].isin(["won", "lost"])]
    if not opp.empty:
        hit = opp["games_result"] == "won"
        odds = pd.to_numeric(opp["games_odds"], errors="coerce")
        priced = odds.notna()
        text = f"adversarul sub 6.5: {hit.sum()} din {len(opp)} ({hit.mean():.0%})"
        if priced.any():
            text += f", profit {float((odds[priced] - 1).where(hit[priced], -1).sum()):+.2f}u pe cele {priced.sum()} cu cota"
        parts.append(text)
    if not parts:
        return ""
    return "<p style='color:#555;'><b>Pana acum:</b> " + " | ".join(parts) + "</p>"


def email_section_html(picks: pd.DataFrame, models: dict[str, Model]) -> str:
    head = ("<h3 style='margin-top:24px;'>Model 90% (URMARIRE PE HARTIE)</h3>"
            "<p style='color:#555;'>Model statistic antrenat doar pe istoricul jucatorilor (fara cote). "
            "Pragul e ales zilnic ca sa dea &ge; 90% pe ultimele 3 saptamani, pe care modelul nu le-a vazut. ")
    head += "; ".join(
        f"{MARKETS[t]}: prag {m.threshold}, {m.validation_rate:.0%} din {m.validation_picks} in validare"
        if m.threshold is not None else f"{MARKETS[t]}: 90% neatins in validare, nicio alegere"
        for t, m in models.items()) + ".</p>"
    if picks.empty:
        return head + "<p><i>Nicio alegere azi.</i></p>" + summary_html()
    html = [head]
    for target in MARKETS:
        sel = picks[picks["market"] == MARKETS[target]]
        html.append(f"<p><b>{MARKETS[target].capitalize()} ({len(sel)}):</b></p>")
        if sel.empty:
            continue
        html.append("<ul>")
        for _, c in sel.iterrows():
            if target == TARGET_WIN:
                bet = f"<b>{c.recommended_player}</b> castiga @ {c.rec_odds}"
            else:
                odds = f" @ {c.games_odds}" if pd.notna(c.games_odds) and c.games_odds else " (cota Sub 6.5 indisponibila)"
                bet = f"<b>{c.opponent}</b> sub 6.5 game-uri{odds} (castiga clar {c.recommended_player})"
            html.append(f"<li>{bet} | model {c.probability:.0%} | vs {c.opponent if target == TARGET_WIN else c.recommended_player}"
                        f" ({c.tour}, ora {c.time})</li>")
        html.append("</ul>")
    return "".join(html) + summary_html()
