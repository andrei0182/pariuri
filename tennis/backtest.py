"""Backtest al estimarii compuse pe meciuri deja jucate.

Pentru fiecare zi din interval: citeste pagina /results/ de pe TennisExplorer
(atp-single + wta-single - includ Challenger/ITF/WTA 125), apoi pentru un
esantion de meciuri terminate descarca pagina match-detail si reconstruieste
ce am fi stiut INAINTE de meci:
- forma recenta: doar meciurile cu data < ziua meciului
- H2H: fara meciul insusi (exclus dupa match_id)
- recordul pe suprafata (sezon): scadem meciul insusi

Scurgeri de informatie ramase (documentate, nu ascunse): rank-ul e cel de
AZI, nu cel din ziua meciului, iar recordul pe suprafata include si
meciurile jucate dupa meciul testat. Pe un interval de 1-3 saptamani in
urma efectul e mic, dar favorizeaza usor modelul - de tinut minte cand
citim rezultatele.

Compara mai multe variante (doar rank, modelul vechi, modelul nou) si,
DOAR CA ETALON, cotele medii afisate de TennisExplorer - cotele nu intra
in niciun model. Mai invata si ponderile semnalelor (regresie logistica),
in loc sa le alegem de mana.

Ruleaza din CI (proxy-ul sesiunii de dezvoltare blocheaza TennisExplorer):
    python backtest.py --days 14 --max-matches 600
Scrie stats/backtest_report.md si stats/backtest_rows.csv."""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from bs4 import BeautifulSoup

import main
from tenis_scraper import tennisexplorer as te

logger = logging.getLogger(__name__)

RESULTS_URL = te.BASE_URL + "/results/"
TOUR_TYPES = ("atp-single", "wta-single")
REPORT_PATH = Path("stats") / "backtest_report.md"
ROWS_PATH = Path("stats") / "backtest_rows.csv"


@dataclass
class ResultRow:
    date: dt.date
    tour_type: str
    tournament: str
    match_id: int
    odds_first: float | None  # cota primului jucator listat (castigatorul, pe /results/)
    odds_second: float | None


def parse_results_page(html: str, date: dt.date, tour_type: str) -> list[ResultRow]:
    """CONFIRMAT 2026-09-23 (tools/samples/results_*.html): table.result cu
    randuri "head flags" per turneu, apoi cate 2 <tr> per meci (id rN / rNb).
    Primul rand are td.result, td.course/coursew cu cotele H/A si linkul
    match-detail. Dublul are "/" in nume si e sarit."""
    soup = BeautifulSoup(html, "lxml")
    rows: list[ResultRow] = []
    for table in soup.find_all("table", class_="result"):
        tournament = ""
        for tr in table.find_all("tr"):
            classes = tr.get("class") or []
            if "head" in classes:
                name = tr.find("td", class_="t-name")
                tournament = name.get_text(strip=True) if name else tournament
                continue
            link = tr.find("a", href=re.compile(r"/match-detail/"))
            if link is None:
                continue
            names = tr.find("td", class_="t-name")
            if names is None or "/" in names.get_text():
                continue
            match_id = te.find_match_id_from_gamedetail_link(link["href"])
            odds = [c.get_text(strip=True) for c in tr.find_all("td", class_=["course", "coursew"])]
            odds_f = [float(o) for o in odds if re.fullmatch(r"\d+\.\d+", o)]
            if match_id is None:
                continue
            rows.append(ResultRow(
                date=date, tour_type=tour_type, tournament=tournament, match_id=match_id,
                odds_first=odds_f[0] if len(odds_f) == 2 else None,
                odds_second=odds_f[1] if len(odds_f) == 2 else None,
            ))
    return rows


def fetch_results(date: dt.date, tour_type: str) -> list[ResultRow]:
    params = {"type": tour_type, "year": date.year, "month": f"{date.month:02d}", "day": f"{date.day:02d}"}
    try:
        resp = te._session.get(RESULTS_URL, params=params, timeout=20)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("results %s %s: %s", tour_type, date, exc)
        return []
    return parse_results_page(resp.text, date, tour_type)


def _subtract_match_from_balance(
    balance: dict[str, tuple[str, str]], surface: str, p1_won: bool
) -> dict[str, tuple[str, str]]:
    """Scoate meciul testat din recordul pe suprafata al ambilor jucatori."""
    out = dict(balance)
    key = next((k for k in balance if k.lower() == surface.lower()), None)
    if key is None:
        return out
    fixed = []
    for idx, won in ((0, p1_won), (1, not p1_won)):
        rec = main._parse_record(balance[key][idx])
        if rec is None:
            fixed.append(balance[key][idx])
            continue
        w, l = rec
        w, l = (max(w - 1, 0), l) if won else (w, max(l - 1, 0))
        fixed.append(f"{w}/{l}")
    out[key] = (fixed[0], fixed[1])
    return out


def pre_match_signals(detail: te.MatchDetailData, match_id: int, match_date: dt.date) -> dict | None:
    """Toate semnalele, asa cum ar fi aratat inainte de meci. None daca
    meciul nu s-a terminat normal (nejucat sau abandon)."""
    if not detail.set_scores or detail.retired:
        return None
    sets1 = sum(1 for a, b in detail.set_scores if a > b)
    sets2 = sum(1 for a, b in detail.set_scores if b > a)
    if sets1 == sets2:
        return None
    p1_won = sets1 > sets2

    def before(matches: list[te.RecentMatch]) -> list[te.RecentMatch]:
        return [m for m in matches if (d := main._parse_recent_match_date(m)) is not None and d < match_date]

    recent1, recent2 = before(detail.player1_recent), before(detail.player2_recent)
    balance = _subtract_match_from_balance(detail.surface_balance, detail.surface, p1_won)

    rank1, rank2 = main._parse_rank(detail.player1.ranking), main._parse_rank(detail.player2.ranking)
    rank_p = main._rank_probability(rank1, rank2)
    form_old = main._form_probability(*te.form_win_loss(recent1), *te.form_win_loss(recent2))
    form_new = main._form_probability(*main._weighted_form(recent1), *main._weighted_form(recent2))
    career_p, career_conf = main._career_rating_probability(balance)
    surface_p, surface_conf = main._surface_rating_probability(balance, detail.surface)
    h2h_p, h2h_w = main._h2h_probability(
        detail.h2h_matches, detail.player1.name, detail.surface, match_date.year, exclude_match_id=match_id,
    )
    n1 = main._matches_played_within(recent1, match_date)
    n2 = main._matches_played_within(recent2, match_date)
    fatigue_pp = main._fatigue_penalty_pp(n2) - main._fatigue_penalty_pp(n1)

    def with_fatigue(p: float | None) -> float | None:
        return None if p is None else min(max(p + fatigue_pp / 100, 0.0), 1.0)

    return {
        "p1_won": int(p1_won),
        "surface": detail.surface,
        "rank_p": rank_p,
        "form_old_p": form_old,
        "form_new_p": form_new,
        "career_p": career_p,
        "career_conf": career_conf,
        "surface_p": surface_p,
        "surface_conf": surface_conf,
        "h2h_p": h2h_p,
        "h2h_w": h2h_w,
        "fatigue_pp": fatigue_pp,
        "model_old": with_fatigue(main._composite_estimate(rank_p, form_old, career_p, career_conf)),
        "model_new": with_fatigue(main._composite_estimate(rank_p, form_new, surface_p, surface_conf, h2h_p, h2h_w)),
        "p1_name": detail.player1.name,
        "p2_name": detail.player2.name,
    }


def _market_p1(row: ResultRow, detail: te.MatchDetailData, p1_won: bool) -> float | None:
    """Pe /results/ primul jucator listat e castigatorul - intoarcem cota
    implicita (fara marja) pentru player1 de pe pagina match-detail."""
    if row.odds_first is None or row.odds_second is None:
        return None
    winner_p = main._implied_probability(row.odds_first, row.odds_second)
    if winner_p is None:
        return None
    return winner_p if p1_won else 1 - winner_p


PROB_COLUMNS = (
    "rank_p", "form_old_p", "form_new_p", "career_p", "surface_p", "h2h_p", "model_old", "model_new", "market_p",
)


def flip_perspective(signals: dict) -> dict:
    """Aceleasi date, vazute din partea celuilalt jucator. Necesar pentru ca
    TennisExplorer pune castigatorul primul (CONFIRMAT pe /results/: 414/414
    meciuri) - fara amestecare, "jucatorul 1" ar castiga mereu si orice
    metrica ar iesi falsa."""
    out = dict(signals)
    for col in PROB_COLUMNS:
        if out.get(col) is not None:
            out[col] = 1 - out[col]
    out["p1_won"] = 1 - out["p1_won"]
    out["fatigue_pp"] = -out["fatigue_pp"]
    out["p1_name"], out["p2_name"] = out["p2_name"], out["p1_name"]
    return out


# ---------------------------------------------------------------- metrici

def _clip(p: np.ndarray) -> np.ndarray:
    return np.clip(p, 1e-4, 1 - 1e-4)


def score(p: np.ndarray, y: np.ndarray) -> dict:
    p = _clip(p)
    return {
        "n": len(y),
        "accuracy": float(np.mean((p > 0.5) == (y == 1))),
        "brier": float(np.mean((p - y) ** 2)),
        "log_loss": float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))),
    }


def calibration_table(p: np.ndarray, y: np.ndarray) -> list[tuple[str, int, float, float]]:
    """Pe partea favorizata de model (p sau 1-p >= 0.5): cat estima modelul
    in medie vs cat s-a intamplat de fapt, pe intervale de 10 puncte."""
    fav_p = np.where(p >= 0.5, p, 1 - p)
    fav_won = np.where(p >= 0.5, y, 1 - y)
    out = []
    for lo in (0.5, 0.6, 0.7, 0.8, 0.9):
        mask = (fav_p >= lo) & (fav_p < lo + 0.1 if lo < 0.9 else fav_p <= 1.0)
        if mask.sum():
            out.append((f"{int(lo*100)}-{int(lo*100)+10}%", int(mask.sum()), float(fav_p[mask].mean()), float(fav_won[mask].mean())))
    return out


def _logit(p: np.ndarray) -> np.ndarray:
    p = _clip(p)
    return np.log(p / (1 - p))


FEATURES = ["rank_p", "form_new_p", "surface_p", "h2h_p", "fatigue_pp"]


def fit_logistic(df: pd.DataFrame, l2: float = 1.0, steps: int = 3000, lr: float = 0.1) -> dict[str, float]:
    """Regresie logistica fara intercept (simetrica: schimbarea ordinii
    jucatorilor intoarce predictia) pe logit-urile semnalelor. Semnal lipsa
    = logit 0 (50%, fara informatie). Oboseala intra liniar, in puncte/10."""
    X = np.column_stack([
        _logit(df[f].fillna(0.5).to_numpy(dtype=float)) if f != "fatigue_pp" else df[f].fillna(0).to_numpy(dtype=float) / 10
        for f in FEATURES
    ])
    y = df["p1_won"].to_numpy(dtype=float)
    w = np.zeros(X.shape[1])
    for _ in range(steps):
        p = 1 / (1 + np.exp(-X @ w))
        grad = X.T @ (p - y) / len(y) + l2 * w / len(y)
        w -= lr * grad
    return dict(zip(FEATURES, w.tolist()))


def predict_logistic(df: pd.DataFrame, weights: dict[str, float]) -> np.ndarray:
    z = np.zeros(len(df))
    for f, wt in weights.items():
        col = df[f].fillna(0.5 if f != "fatigue_pp" else 0).to_numpy(dtype=float)
        z += wt * (_logit(col) if f != "fatigue_pp" else col / 10)
    return 1 / (1 + np.exp(-z))


# ---------------------------------------------------------------- raport

def build_report(df: pd.DataFrame, start: dt.date, end: dt.date) -> str:
    y = df["p1_won"].to_numpy(dtype=float)
    lines = [
        f"# Backtest tenis — {start} … {end}",
        "",
        f"Meciuri testate: **{len(df)}** (simplu, terminate normal, ATP/WTA/Challenger/ITF).",
        "",
        "Scurgeri de informatie ramase: rank-ul e cel actual, iar recordul pe suprafata "
        "include si meciuri jucate dupa cel testat. Ambele favorizeaza usor modelele, nu piata.",
        "",
        "## Comparatie (pe meciurile unde toate variantele au o estimare)",
        "",
        "| Varianta | Meciuri | Acuratete | Brier ↓ | Log-loss ↓ |",
        "|---|---|---|---|---|",
    ]
    variants = {
        "Doar rank": "rank_p",
        "Model vechi (rank + forma + record general)": "model_old",
        "Model nou (+ suprafata, H2H, forma ponderata)": "model_new",
        "Piata (cote medii TennisExplorer) — doar etalon": "market_p",
    }
    common = df.dropna(subset=list(variants.values()))
    yc = common["p1_won"].to_numpy(dtype=float)
    for label, col in variants.items():
        s = score(common[col].to_numpy(dtype=float), yc)
        lines.append(f"| {label} | {s['n']} | {s['accuracy']:.1%} | {s['brier']:.4f} | {s['log_loss']:.4f} |")

    # ponderi invatate - jumatate antrenare, jumatate test (in ordine cronologica)
    ordered = df.sort_values("date")
    half = len(ordered) // 2
    train, test = ordered.iloc[:half], ordered.iloc[half:]
    weights = fit_logistic(train)
    learned = score(predict_logistic(test, weights), test["p1_won"].to_numpy(dtype=float))
    test_common = test.dropna(subset=["model_new", "market_p"])
    lines += [
        "",
        "## Ponderi invatate din date (regresie logistica)",
        "",
        "Antrenat pe prima jumatate a perioadei, testat pe a doua (fara sa vada rezultatele ei).",
        "",
        "| Semnal | Pondere |",
        "|---|---|",
        *[f"| {f} | {w:+.3f} |" for f, w in weights.items()],
        "",
        f"Pe jumatatea de test ({learned['n']} meciuri): acuratete {learned['accuracy']:.1%}, "
        f"Brier {learned['brier']:.4f}, log-loss {learned['log_loss']:.4f}.",
    ]
    if len(test_common):
        tn = score(test_common["model_new"].to_numpy(dtype=float), test_common["p1_won"].to_numpy(dtype=float))
        tm = score(test_common["market_p"].to_numpy(dtype=float), test_common["p1_won"].to_numpy(dtype=float))
        lines.append(
            f"Pe aceeasi jumatate: model nou Brier {tn['brier']:.4f}, piata Brier {tm['brier']:.4f} "
            f"({len(test_common)} meciuri cu cote)."
        )

    lines += ["", "## Calibrare model nou", "",
              "Cand modelul isi favorizeaza un jucator cu X%, cat de des castiga acel jucator?", "",
              "| Interval estimare | Meciuri | Estimare medie | Castigat de fapt |", "|---|---|---|---|"]
    new_ok = df.dropna(subset=["model_new"])
    for rng, n, est, act in calibration_table(new_ok["model_new"].to_numpy(dtype=float), new_ok["p1_won"].to_numpy(dtype=float)):
        lines.append(f"| {rng} | {n} | {est:.1%} | {act:.1%} |")

    lines += ["", "## Pe suprafete (model nou)", "", "| Suprafata | Meciuri | Acuratete | Brier |", "|---|---|---|---|"]
    for surface, grp in new_ok.groupby("surface"):
        s = score(grp["model_new"].to_numpy(dtype=float), grp["p1_won"].to_numpy(dtype=float))
        lines.append(f"| {surface or 'necunoscuta'} | {s['n']} | {s['accuracy']:.1%} | {s['brier']:.4f} |")

    lines += ["", "Brier: eroarea medie la patrat a probabilitatii (0 = perfect, 0.25 = aruncarea monedei). "
              "Log-loss: pedepseste mai tare increderea mare gresita. La ambele, mai mic e mai bine."]
    return "\n".join(lines) + "\n"


def main_cli() -> None:
    parser = argparse.ArgumentParser(description="Backtest al estimarii compuse pe meciuri jucate.")
    parser.add_argument("--days", type=int, default=14, help="cate zile in urma (se sare peste azi si ieri)")
    parser.add_argument("--max-matches", type=int, default=600, help="plafon de pagini match-detail descarcate")
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    end = dt.date.today() - dt.timedelta(days=2)
    start = end - dt.timedelta(days=args.days - 1)
    candidates: list[ResultRow] = []
    day = start
    while day <= end:
        for tour_type in TOUR_TYPES:
            candidates += fetch_results(day, tour_type)
            time.sleep(args.delay)
        day += dt.timedelta(days=1)
    logger.info("%d meciuri pe paginile /results/ intre %s si %s", len(candidates), start, end)

    rng = random.Random(args.seed)
    rng.shuffle(candidates)
    rows = []
    for i, cand in enumerate(candidates[: args.max_matches]):
        detail = te.fetch_and_parse_match(cand.match_id)
        time.sleep(args.delay)
        if detail is None:
            continue
        signals = pre_match_signals(detail, cand.match_id, cand.date)
        if signals is None:
            continue
        signals.update({
            "date": cand.date.isoformat(), "tour_type": cand.tour_type, "tournament": cand.tournament,
            "match_id": cand.match_id,
            "market_p": _market_p1(cand, detail, bool(signals["p1_won"])),
        })
        rows.append(flip_perspective(signals) if rng.random() < 0.5 else signals)
        if (i + 1) % 50 == 0:
            logger.info("%d/%d pagini procesate, %d meciuri utilizabile", i + 1, min(len(candidates), args.max_matches), len(rows))

    df = pd.DataFrame(rows)
    ROWS_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(ROWS_PATH, index=False)
    report = build_report(df, start, end)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main_cli()
