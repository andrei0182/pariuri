"""Rating Elo general + pe suprafata, calculat din data/results.csv.gz
(vezi history.py), si backtest-ul lui.

Metoda (varianta folosita pe scara larga in tenis, popularizata de
FiveThirtyEight): fiecare jucator are un Elo general si cate unul pe fiecare
suprafata, toti pornind de la 1500. Dupa fiecare meci, ambele se muta cu
K = 250 / (meciuri_jucate + 5) ** 0.4 - jucatorii noi se misca repede,
cei cu multe meciuri incet. Predictia foloseste media dintre Elo-ul general
si cel de pe suprafata meciului. Elo tine cont automat de calitatea
adversarului: o victorie cu un jucator puternic urca mult, una cu unul slab
aproape deloc.

Backtest-ul e cronologic: fiecare meci e prezis DOAR cu ratingurile de
dinaintea lui, apoi ratingurile se actualizeaza - fara nicio scurgere de
informatie. Cotele (media TennisExplorer) apar doar ca etalon si in
simularea de pariere, nu intra in rating.

    python elo.py --eval-days 30
Scrie stats/elo_report.md si stats/elo_ratings.csv."""
from __future__ import annotations

import argparse
import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

import history

START_RATING = 1500.0
REPORT_PATH = Path("stats") / "elo_report.md"
RATINGS_PATH = Path("stats") / "elo_ratings.csv"
MIN_MATCHES_ESTABLISHED = 10


def k_factor(matches_played: int) -> float:
    return 250.0 / (matches_played + 5) ** 0.4


def expected(r_a: float, r_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((r_b - r_a) / 400.0))


@dataclass
class EloBook:
    overall: dict[str, float] = field(default_factory=lambda: defaultdict(lambda: START_RATING))
    surface: dict[tuple[str, str], float] = field(default_factory=lambda: defaultdict(lambda: START_RATING))
    n_overall: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    n_surface: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    names: dict[str, str] = field(default_factory=dict)

    def predict(self, a: str, b: str, surface: str) -> dict[str, float]:
        """Probabilitatea ca `a` sa-l bata pe `b`: general, pe suprafata, combinat."""
        p_overall = expected(self.overall[a], self.overall[b])
        if not surface:
            return {"overall": p_overall, "surface": p_overall, "blend": p_overall}
        p_surface = expected(self.surface[(a, surface)], self.surface[(b, surface)])
        blend_a = (self.overall[a] + self.surface[(a, surface)]) / 2
        blend_b = (self.overall[b] + self.surface[(b, surface)]) / 2
        return {"overall": p_overall, "surface": p_surface, "blend": expected(blend_a, blend_b)}

    def update(self, winner: str, loser: str, surface: str) -> None:
        p = expected(self.overall[winner], self.overall[loser])
        kw, kl = k_factor(self.n_overall[winner]), k_factor(self.n_overall[loser])
        self.overall[winner] += kw * (1 - p)
        self.overall[loser] -= kl * (1 - p)
        self.n_overall[winner] += 1
        self.n_overall[loser] += 1
        if surface:
            ws, ls = (winner, surface), (loser, surface)
            ps = expected(self.surface[ws], self.surface[ls])
            kws, kls = k_factor(self.n_surface[ws]), k_factor(self.n_surface[ls])
            self.surface[ws] += kws * (1 - ps)
            self.surface[ls] -= kls * (1 - ps)
            self.n_surface[ws] += 1
            self.n_surface[ls] += 1


def load_matches() -> pd.DataFrame:
    """Rezultatele, cu suprafata turneului atasata, in ordine cronologica."""
    results = history.load_results()
    surfaces = history.load_surfaces()
    results["surface"] = results["tournament_slug"].map(surfaces).fillna("")
    return results.sort_values(["date", "match_id"]).reset_index(drop=True)


def run(matches: pd.DataFrame, eval_from: str) -> tuple[EloBook, pd.DataFrame]:
    """Trece prin toate meciurile in ordine. Pentru cele de la `eval_from`
    incolo noteaza predictia facuta INAINTE de update (din perspectiva
    castigatorului: p = sansa pe care i-o dadea Elo)."""
    book = EloBook()
    rows = []
    for m in matches.itertuples(index=False):
        w, l, s = m.winner_slug, m.loser_slug, m.surface
        book.names[w], book.names[l] = m.winner_name, m.loser_name
        if m.date >= eval_from:
            pred = book.predict(w, l, s)
            market = None
            if pd.notna(m.odds_winner) and pd.notna(m.odds_loser) and m.odds_winner > 1 and m.odds_loser > 1:
                inv_w, inv_l = 1 / m.odds_winner, 1 / m.odds_loser
                market = inv_w / (inv_w + inv_l)
            rows.append({
                "date": m.date, "match_id": m.match_id, "surface": s, "tour_type": m.tour_type,
                "winner": m.winner_name, "loser": m.loser_name,
                "p_overall": pred["overall"], "p_surface": pred["surface"], "p_blend": pred["blend"],
                "p_market": market, "odds_winner": m.odds_winner, "odds_loser": m.odds_loser,
                "n_winner": book.n_overall[w], "n_loser": book.n_overall[l],
            })
        book.update(w, l, s)
    return book, pd.DataFrame(rows)


# ---------------------------------------------------------------- metrici

def score(p_winner: np.ndarray) -> dict:
    """Metrici din perspectiva castigatorului (y = 1 mereu): Brier si
    log-loss nu depind de ce jucator numim "1"."""
    p = np.clip(p_winner, 1e-4, 1 - 1e-4)
    return {
        "n": len(p),
        "accuracy": float(np.mean(p > 0.5)),
        "brier": float(np.mean((1 - p) ** 2)),
        "log_loss": float(-np.mean(np.log(p))),
    }


def calibration(p_winner: np.ndarray) -> list[tuple[str, int, float, float]]:
    fav_p = np.maximum(p_winner, 1 - p_winner)
    fav_won = p_winner >= 0.5
    out = []
    for lo in (0.5, 0.6, 0.7, 0.8, 0.9):
        hi = lo + 0.1
        mask = (fav_p >= lo) & ((fav_p < hi) if lo < 0.9 else (fav_p <= 1.0))
        if mask.sum():
            out.append((f"{int(lo*100)}-{int(hi*100)}%", int(mask.sum()), float(fav_p[mask].mean()), float(fav_won[mask].mean())))
    return out


def betting_simulation(df: pd.DataFrame, col: str, threshold: float) -> dict:
    """Pariu de 1 unitate pe jucatorul la care Elo da cu >= threshold peste
    piata, la COTELE REALE (cu marja casei inclusa)."""
    d = df.dropna(subset=["p_market"])
    edge_w = d[col] - d["p_market"]  # pozitiv = Elo il vede mai bun pe castigator decat piata
    on_winner = d[edge_w >= threshold]
    on_loser = d[-edge_w >= threshold]
    profit = float((on_winner["odds_winner"] - 1).sum() - len(on_loser))
    bets = len(on_winner) + len(on_loser)
    return {
        "bets": bets,
        "won": len(on_winner),
        "profit": profit,
        "roi": profit / bets if bets else 0.0,
        "avg_odds": float(pd.concat([on_winner["odds_winner"], on_loser["odds_loser"]]).mean()) if bets else 0.0,
    }


def build_report(df: pd.DataFrame, matches_total: int, first_date: str, eval_from: str, last_date: str) -> str:
    est = df[(df["n_winner"] >= MIN_MATCHES_ESTABLISHED) & (df["n_loser"] >= MIN_MATCHES_ESTABLISHED)]
    lines = [
        f"# Elo pe suprafata — backtest {eval_from} … {last_date}",
        "",
        f"Istoric folosit: **{matches_total}** meciuri ({first_date} … {last_date}). Ratingurile se construiesc "
        f"pe tot istoricul; se evalueaza doar meciurile de la {eval_from}, fiecare prezis inainte de update.",
        "",
        "## Cat de bine prezice",
        "",
        "| Varianta | Meciuri | Acuratete | Brier ↓ | Log-loss ↓ |",
        "|---|---|---|---|---|",
    ]
    for subset_label, subset in (("toate", df), (f"ambii cu ≥{MIN_MATCHES_ESTABLISHED} meciuri in istoric", est)):
        common = subset.dropna(subset=["p_market"])
        for label, col in (("Elo general", "p_overall"), ("Elo suprafata", "p_surface"),
                           ("Elo combinat", "p_blend"), ("Piata — doar etalon", "p_market")):
            s = score(common[col].to_numpy(dtype=float))
            lines.append(f"| {label} ({subset_label}) | {s['n']} | {s['accuracy']:.1%} | {s['brier']:.4f} | {s['log_loss']:.4f} |")

    lines += ["", f"## Calibrare Elo combinat (ambii cu ≥{MIN_MATCHES_ESTABLISHED} meciuri)", "",
              "| Interval | Meciuri | Elo estima | Favoritul Elo a castigat |", "|---|---|---|---|"]
    for rng, n, e, a in calibration(est["p_blend"].to_numpy(dtype=float)):
        lines.append(f"| {rng} | {n} | {e:.1%} | {a:.1%} |")

    lines += ["", f"## Simulare de pariere la cotele reale (ambii cu ≥{MIN_MATCHES_ESTABLISHED} meciuri)", "",
              "Pariu de 1 unitate pe jucatorul la care Elo combinat da cu cel putin X puncte peste piata.", "",
              "| Prag | Pariuri | Castigate | Cota medie | Profit | ROI |", "|---|---|---|---|---|---|"]
    for thr in (0.05, 0.10, 0.15, 0.20):
        b = betting_simulation(est, "p_blend", thr)
        won_pct = b["won"] / b["bets"] if b["bets"] else 0
        lines.append(f"| ≥{int(thr*100)}pp | {b['bets']} | {won_pct:.0%} | {b['avg_odds']:.2f} | {b['profit']:+.1f}u | {b['roi']:+.1%} |")

    lines += ["", "## Pe suprafete (Elo combinat, toate meciurile)", "", "| Suprafata | Meciuri | Acuratete | Brier |", "|---|---|---|---|"]
    for surface, grp in df.groupby("surface"):
        s = score(grp["p_blend"].to_numpy(dtype=float))
        lines.append(f"| {surface or 'necunoscuta'} | {s['n']} | {s['accuracy']:.1%} | {s['brier']:.4f} |")
    lines += ["", "Brier: 0 = perfect, 0.25 = aruncarea monedei. Mai mic e mai bine."]
    return "\n".join(lines) + "\n"


def ratings_table(book: EloBook) -> pd.DataFrame:
    rows = []
    for player, rating in book.overall.items():
        row = {"player_slug": player, "name": book.names.get(player, ""), "elo": round(rating, 1),
               "matches": book.n_overall[player]}
        for surface in ("Hard", "Clay", "Grass", "Indoors"):
            if (player, surface) in book.surface:
                row[f"elo_{surface.lower()}"] = round(book.surface[(player, surface)], 1)
                row[f"matches_{surface.lower()}"] = book.n_surface[(player, surface)]
        rows.append(row)
    return pd.DataFrame(rows).sort_values("elo", ascending=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Elo pe suprafata + backtest.")
    parser.add_argument("--eval-days", type=int, default=30, help="cate zile de la final se evalueaza")
    args = parser.parse_args()

    matches = load_matches()
    last_date = str(matches["date"].max())
    first_date = str(matches["date"].min())
    eval_from = (dt.date.fromisoformat(last_date) - dt.timedelta(days=args.eval_days - 1)).isoformat()
    book, df = run(matches, eval_from)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = build_report(df, len(matches), first_date, eval_from, last_date)
    REPORT_PATH.write_text(report, encoding="utf-8")
    ratings_table(book).to_csv(RATINGS_PATH, index=False)
    print(report)


if __name__ == "__main__":
    main()
