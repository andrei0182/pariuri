"""Analiza pe ISTORICUL JUCATORILOR (nu pe cote) - URMARIRE PE HARTIE.

Pentru fiecare meci din raportul zilei se alege jucatorul mai bun dupa
procentul de game-uri castigate pe suprafata meciului, apoi se verifica
daca restul indicatorilor sunt de acord:
- victorii pe suprafata, forma (ultimele 10 meciuri), Elo (elo.py)
- meciuri directe (H2H) si adversari comuni (>= 2), cand exista
Cota intra DOAR la final: in email apar ca recomandari doar alegerile cu
cota >= MIN_ODDS. Toate alegerile (inclusiv sub prag) se logheaza in
stats/player_history_log.csv; check_results.py completeaza rezultatul
(castigator) si pariul "peste GAMES_LINE game-uri" pe jucatorul ales.

Simulare 2026-10-11 pe istoric (mai-oct 2026): cand toti indicatorii sunt
de acord, ~73-80% castigate; la cote >= 1.5 rata scade (piata stie si ea).
Prima zi reala (2026-10-11): 2 din 6 la cote >= 1.5."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

import elo
import underdog

LOG_PATH = Path("stats") / "player_history_log.csv"
LOG_COLUMNS = [
    "date", "tournament", "tour", "surface", "player1", "player2", "recommended_player", "opponent",
    "verdict", "rec_odds", "odds_pass", "elo_pct", "details", "games_line", "games_odds",
    "te_match_id", "result", "score", "checked_at", "set_scores", "rec_games", "games_result",
]
MIN_ODDS = 1.5
GAMES_LINE = 8.5            # in simulare, "acord puternic": 92.5% au facut peste 8.5 game-uri
MIN_SURFACE_GAMES = 40      # game-uri jucate pe suprafata ca sa avem un procent
MIN_SURFACE_MATCHES = 5
MIN_COMMON = 2
AGREE, MOSTLY, MIXED, NO_DATA = "toti de acord", "mai ales da", "contradictoriu", "istoric insuficient"

# Coloanele raportului Excel (main._COLUMN_LABELS)
_P1, _P2 = "Jucător 1", "Jucător 2"
_ODDS = {1: "Cotă 1", 2: "Cotă 2"}
_SLUG = {1: "TennisExplorer J1", 2: "TennisExplorer J2"}
_LINES = {1: "Linii Game-uri J1 (linie@cotă Peste)", 2: "Linii Game-uri J2 (linie@cotă Peste)"}
_SURFACE, _TOUR, _TOURNAMENT, _TIME, _TE_ID = "Suprafață Meci", "Tur", "Turneu", "Ora", "TennisExplorer match_id"


@dataclass
class History:
    book: elo.EloBook
    surf_wl: dict = field(default_factory=lambda: defaultdict(lambda: [0, 0]))
    surf_games: dict = field(default_factory=lambda: defaultdict(lambda: [0, 0]))
    vs: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(lambda: [0, 0])))
    last: dict = field(default_factory=lambda: defaultdict(list))
    itf: dict = field(default_factory=lambda: defaultdict(lambda: [0, 0]))


def build_history(matches: pd.DataFrame | None = None) -> History:
    """Toti indicatorii, din data/results.csv.gz (cu suprafata atasata)."""
    matches = elo.load_matches() if matches is None else matches
    book, _ = elo.run(matches, eval_from="9999")
    h = History(book)
    for r in matches.itertuples(index=False):
        w, l, s = r.winner_slug, r.loser_slug, r.surface
        sets = [tuple(map(int, x.split("-"))) for x in str(r.score).split()]
        gw, gl = sum(a for a, _ in sets), sum(b for _, b in sets)
        h.surf_wl[(w, s)][0] += 1
        h.surf_wl[(l, s)][1] += 1
        h.surf_games[(w, s)][0] += gw
        h.surf_games[(w, s)][1] += gl
        h.surf_games[(l, s)][0] += gl
        h.surf_games[(l, s)][1] += gw
        h.vs[w][l][0] += 1
        h.vs[l][w][1] += 1
        h.last[w].append(1)
        h.last[l].append(0)
        is_itf = underdog.history_level(r.tournament) == "ITF"
        for p in (w, l):
            h.itf[p][0] += is_itf
            h.itf[p][1] += 1
    return h


def player_stats(h: History, slug: str, surface: str) -> dict:
    wl, g = h.surf_wl[(slug, surface)], h.surf_games[(slug, surface)]
    recent = h.last[slug][-10:]
    return {
        "wl": wl,
        "win_rate": wl[0] / sum(wl) if sum(wl) >= MIN_SURFACE_MATCHES else np.nan,
        "games": g[0] / sum(g) if sum(g) >= MIN_SURFACE_GAMES else np.nan,
        "recent": recent,
        "form": np.mean(recent) if len(recent) >= 5 else np.nan,
        "itf_share": h.itf[slug][0] / h.itf[slug][1] if h.itf[slug][1] else np.nan,
    }


def assess(h: History, x: str, y: str, surface: str) -> dict:
    """Verdictul pentru jucatorul x (deja ales ca mai bun pe suprafata) vs y."""
    X, Y = player_stats(h, x, surface), player_stats(h, y, surface)
    p_elo = h.book.predict(x, y, surface)["blend"]
    h2h_x, h2h_y = h.vs[x][y]
    common = (set(h.vs[x]) & set(h.vs[y])) - {x, y}
    co = np.nan
    if len(common) >= MIN_COMMON:
        co = (np.mean([h.vs[x][c][0] / sum(h.vs[x][c]) for c in common])
              - np.mean([h.vs[y][c][0] / sum(h.vs[y][c]) for c in common]))
    games_diff = X["games"] - Y["games"]
    both_wr = not (np.isnan(X["win_rate"]) or np.isnan(Y["win_rate"]))
    checks = [  # (nume, pentru, contra)
        ("game-uri pe suprafata", games_diff >= 0.05, games_diff < 0.02),
        ("victorii pe suprafata", both_wr and X["win_rate"] > Y["win_rate"], both_wr and X["win_rate"] < Y["win_rate"]),
        ("forma", X["form"] > Y["form"], X["form"] < Y["form"]),
        ("Elo", p_elo >= 0.6, p_elo < 0.5),
    ]
    if h2h_x + h2h_y:
        checks.append(("H2H", h2h_x > h2h_y, h2h_x < h2h_y))
    if not np.isnan(co):
        checks.append(("adversari comuni", co > 0.1, co < -0.1))
    pro = sum(1 for _, ok, _ in checks if ok)
    against = [name for name, ok, bad in checks if bad and not ok]
    notes = [f"contra: {n}" for n in against]
    # un istoric facut mai ales in ITF umfla recordul (adversari mai slabi)
    level_warn = bool(X["itf_share"] - Y["itf_share"] > 0.4)
    if level_warn:
        notes.append("istoricul ei/lui e mai ales ITF")
    if not against and pro == len(checks) and games_diff >= 0.08 and not level_warn:
        verdict = AGREE
    elif len(against) <= 1 and pro >= len(checks) - 1 and not level_warn:
        verdict = MOSTLY
    else:
        verdict = MIXED

    def rec(s):
        return f"{sum(s['recent'])}-{len(s['recent']) - sum(s['recent'])}"
    details = (f"{surface}: {X['wl'][0]}-{X['wl'][1]} vs {Y['wl'][0]}-{Y['wl'][1]}, "
               f"game-uri {X['games']:.0%} vs {Y['games']:.0%}; forma {rec(X)} vs {rec(Y)}; Elo {p_elo:.0%}"
               + (f"; H2H {h2h_x}-{h2h_y}" if h2h_x + h2h_y else "")
               + (f"; adversari comuni ({len(common)}) {co:+.0%}" if not np.isnan(co) else "")
               + (f" [{', '.join(notes)}]" if notes else ""))
    return {"verdict": verdict, "elo_pct": round(100 * p_elo, 1), "details": details}


def _ro_time(value) -> str:
    """Ora din raport e UTC (ca la Superbet) -> ora Romaniei, "HH:MM"."""
    try:
        ts = pd.Timestamp(value)
        return ts.tz_localize("UTC").tz_convert("Europe/Bucharest").strftime("%H:%M")
    except (ValueError, TypeError):
        return ""


def _games_odds(lines_text, line: float):
    m = re.search(rf"(?:^|;\s*){re.escape(f'{line:g}')}@(\d+(?:\.\d+)?)", str(lines_text or ""))
    return float(m.group(1)) if m else None


def analyze(df: pd.DataFrame, h: History) -> pd.DataFrame:
    """Un rand per meci cu istoric suficient. Sortat: verdict, apoi cota."""
    rows = []
    for _, r in df.iterrows():
        slugs = {1: r.get(_SLUG[1]), 2: r.get(_SLUG[2])}
        if not all(isinstance(s, str) and s for s in slugs.values()):
            continue
        surface = r.get(_SURFACE)
        surface = surface.strip().capitalize() if isinstance(surface, str) else ""
        g1 = player_stats(h, slugs[1], surface)["games"]
        g2 = player_stats(h, slugs[2], surface)["games"]
        if not surface or np.isnan(g1) or np.isnan(g2):
            continue
        side = 1 if g1 >= g2 else 2
        other = 3 - side
        a = assess(h, slugs[side], slugs[other], surface)
        odds = r.get(_ODDS[side])
        odds = float(odds) if pd.notna(odds) else None
        names = {1: r.get(_P1), 2: r.get(_P2)}
        rows.append({
            "tournament": r.get(_TOURNAMENT, ""), "tour": r.get(_TOUR, ""), "surface": surface,
            "time": _ro_time(r.get(_TIME)),
            "player1": names[1], "player2": names[2],
            "recommended_player": names[side], "opponent": names[other],
            "verdict": a["verdict"], "rec_odds": odds,
            "odds_pass": odds is not None and odds >= MIN_ODDS,
            "elo_pct": a["elo_pct"], "details": a["details"],
            "games_line": GAMES_LINE, "games_odds": _games_odds(r.get(_LINES[side]), GAMES_LINE),
            "te_match_id": r.get(_TE_ID),
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    order = {AGREE: 0, MOSTLY: 1, MIXED: 2}
    return out.sort_values(["verdict", "rec_odds"], key=lambda c: c.map(order) if c.name == "verdict" else -c.fillna(0))


def log_picks(analysis: pd.DataFrame, date_str: str) -> None:
    """Logheaza alegerile "toti de acord" si "mai ales da" (orice cota)."""
    if analysis.empty:
        return
    picks = analysis[analysis["verdict"].isin([AGREE, MOSTLY])].copy()
    if picks.empty:
        return
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log = pd.read_csv(LOG_PATH, dtype=str) if LOG_PATH.exists() else pd.DataFrame(columns=LOG_COLUMNS)
    picks["date"] = date_str
    picks["result"] = "pending"
    for c in ("score", "checked_at", "set_scores", "rec_games", "games_result"):
        picks[c] = ""
    picks = picks[LOG_COLUMNS].astype(str).replace({"None": "", "nan": ""})
    if not log.empty:
        seen = set(zip(log["date"], log["recommended_player"]))
        picks = picks[[(d, p) not in seen for d, p in zip(picks["date"], picks["recommended_player"])]]
    pd.concat([log, picks], ignore_index=True).to_csv(LOG_PATH, index=False)


def summary_html() -> str:
    """Rezultatele reale de pana acum, pe verdict, doar la cota >= MIN_ODDS."""
    if not LOG_PATH.exists():
        return ""
    log = pd.read_csv(LOG_PATH, dtype=str)
    log = log[log["odds_pass"] == "True"]
    parts = []
    for verdict in (AGREE, MOSTLY):
        done = log[(log["verdict"] == verdict) & log["result"].isin(["won", "lost"])]
        if done.empty:
            continue
        won = done["result"] == "won"
        odds = pd.to_numeric(done["rec_odds"], errors="coerce")
        profit = float((odds - 1).where(won, -1).sum())
        parts.append(f"{verdict}: {won.sum()} din {len(done)} castigate ({won.mean():.0%}), profit {profit:+.2f}u")
    if not parts:
        return ""
    return f"<p style='color:#555;'><b>Pana acum (cota &ge; {MIN_ODDS}):</b> " + " | ".join(parts) + "</p>"


def email_section_html(analysis: pd.DataFrame) -> str:
    head = ("<h3 style='margin-top:24px;'>Analiza pe istoricul jucatorilor (URMARIRE PE HARTIE)</h3>"
            "<p style='color:#555;'>Jucatorul mai bun dupa istoric pe suprafata (game-uri si victorii), "
            "forma, Elo, meciuri directe si adversari comuni. Cota e folosita doar la final: "
            f"recomandari doar la cota &ge; {MIN_ODDS}.</p>")
    if analysis.empty:
        return head + "<p><i>Niciun meci cu istoric suficient azi.</i></p>" + summary_html()
    html = [head]
    for verdict, title in ((AGREE, "Toti indicatorii de acord"), (MOSTLY, "Majoritatea de acord (mai riscant)")):
        sel = analysis[(analysis["verdict"] == verdict) & analysis["odds_pass"]]
        html.append(f"<p><b>{title} ({len(sel)}):</b></p>")
        if sel.empty:
            html.append("<p><i>niciunul azi</i></p>")
            continue
        html.append("<ul>")
        for _, c in sel.iterrows():
            games = f", peste {c.games_line:g} game-uri @ {c.games_odds}" if pd.notna(c.games_odds) and c.games_odds else ""
            html.append(f"<li><b>{c.recommended_player}</b> @ {c.rec_odds} vs {c.opponent} ({c.tour}, ora {c.time}){games}"
                        f"<br><span style='color:#555;'>{c.details}</span></li>")
        html.append("</ul>")
    low = analysis[(analysis["verdict"] == AGREE) & ~analysis["odds_pass"]]
    if not low.empty:
        html.append(f"<p style='color:#555;'>Toti de acord, dar cota sub {MIN_ODDS}: "
                    + ", ".join(f"{c.recommended_player} @ {c.rec_odds}" for _, c in low.iterrows()) + "</p>")
    return "".join(html) + summary_html()
