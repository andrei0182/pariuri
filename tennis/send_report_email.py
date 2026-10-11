"""Trimite raportul zilnic de tenis pe email — atasat ca Excel, plus un
rezumat HTML in corpul mesajului cu DOAR meciurile care trec de filtrele
de mai jos (nu toata lista, la fel ca la proiectul SuperBet care filtra
pe "100% Over 2.5" istoric).

Filtre aplicate (schimbate 2026-10-11, vezi MODEL_WEIGHT):
  - estimarea combinata (piata + 30% din model) cu >= MIN_BLEND_EDGE_PP
    peste cota implicita Superbet si >= MIN_BLEND_PCT
  - cota <= MAX_ODDS, fara turnee ITF/UTR
  - edge brut <= MAX_EDGE_PP si estimare proprie <= MAX_COMPOSITE_PCT:
    peste astea e aproape sigur o eroare de date (ex. Insfran vs Santos,
    2026-09-23: edge 88.6pp, estimare 97% la cota 11.0), nu value real.
    Meciurile respective apar separat in email, ca "suspecte", si NU se
    logheaza in picks_log.csv.

Acelasi tipar ca send-email-ul din proiectul SuperBet
(daily_recommendations.py): Gmail SMTP, credentiale din variabile de
mediu (GitHub Secrets in workflow, niciodata comise in repo).

Env vars necesare:
  GMAIL_ADDRESS       contul Gmail care trimite
  GMAIL_APP_PASSWORD  un "App Password" Gmail (NU parola normala a
                       contului) — vezi README pentru cum se genereaza
  EMAIL_TO            adresa destinatarului (poate fi acelasi cont)
"""
from __future__ import annotations

import argparse
import csv
import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import pandas as pd

import underdog

# Regulile din 2026-10-11, dupa analiza a 172 de pick-uri reale si a 67.784
# de meciuri din data/results.csv.gz (Elo ca model, cote TennisExplorer):
# - vechiul filtru (edge brut >= 15pp, estimare >= 55%) alegea aproape doar
#   outsideri (cota medie 2.94): pe pick-uri modelul estima 57%, piata 35%,
#   au castigat 30%. Pe istoric acelasi stil: ROI -12%.
# - outsiderii la cota >= 2 pierd 14-21% pe orice nivel, favoritii la cota
#   < 1.4 doar ~2% (marja casei).
# De aceea: estimarea de selectie e piata + 30% din parerea modelului, cerem
# ca jucatorul sa fie vazut castigator (>= 50%), cota <= 2.0 si fara ITF/UTR.
# Pe istoric (Elo), varianta asta a iesit intre -7% si +1% - mai bine decat
# -12%, dar tot NU sigur pe plus. Raman EXPERIMENTALE.
MODEL_WEIGHT = 0.3
MIN_BLEND_EDGE_PP = 5.0
MIN_BLEND_PCT = 50.0
MAX_ODDS = 2.0
EXCLUDED_TOURS = {"itf-m", "itf-f", "utr-m", "utr-f"}
# Plafoane pentru date stricate (2026-09-23): peste ele modelul e aproape sigur
# gresit (ex. Insfran vs Santos: edge 88.6pp, estimare 97% la cota 11.0).
MAX_EDGE_PP = 50.0
MAX_COMPOSITE_PCT = 85.0

_COL_P1, _COL_P2 = "Jucător 1", "Jucător 2"
_COL_ODDS1, _COL_ODDS2 = "Cotă 1", "Cotă 2"
_COL_COMP1, _COL_COMP2 = "% Estimare Compusă J1 (rank+formă+rating)", "% Estimare Compusă J2 (rank+formă+rating)"
_COL_IMPL1, _COL_IMPL2 = "% Implicit Cotă J1", "% Implicit Cotă J2"
_COL_RATING_CONF = "Încredere rating carieră (0-1)"
_COL_TOURNAMENT, _COL_TIME, _COL_URL = "Turneu", "Ora", "Link Superbet"
_COL_GAMES_LINE_P1 = "Linie Minimă Disponibilă Total Game-uri J1 (meci întreg)"
_COL_GAMES_ODDS_P1 = "Cotă Peste la Linia Minimă J1"
_COL_GAMES_LINE_P2 = "Linie Minimă Disponibilă Total Game-uri J2 (meci întreg)"
_COL_GAMES_ODDS_P2 = "Cotă Peste la Linia Minimă J2"
_COL_TE_MATCH_ID = "TennisExplorer match_id"
_COL_TOUR = "Tur"

PICKS_LOG_PATH = Path("stats") / "picks_log.csv"
PICKS_LOG_COLUMNS = [
    "date", "tournament", "player1", "player2", "recommended_player", "opponent",
    "edge_pp", "rec_odds", "comp_pct", "games_line", "games_odds",
    "te_match_id", "result", "score", "checked_at",
    "set_scores", "rec_games", "games_result", "games_excluded", "blend_pct", "rules",
]
# Versiunea regulilor de selectie, scrisa in picks_log.csv: statistica din
# email arata separat pick-urile facute cu regulile curente.
RULES_VERSION = "v2"

# Analiza din 2026-10-09 pe 149 de pariuri "Peste X game-uri" logate: liniile
# 8-9.5 au iesit in 46% din cazuri (impreuna cu cotele > 1.70: 68 de pariuri,
# ROI -24%), restul in 65% (81 de pariuri, ROI +4%). Pick-ul ramane in email,
# dar linia de game-uri e marcata EXCLUS si nu intra in statistica.
# 2026-10-11: extins la 10 (liniile 8-10: 57 de pariuri, 44% iesite, -16u).
GAMES_EXCLUDED_LINE_RANGE = (8.0, 10.0)
GAMES_MAX_ODDS = 1.70


def games_exclusion_reason(line, odds) -> str:
    """"" daca linia de game-uri e ok, altfel motivul excluderii."""
    try:
        line, odds = float(line), float(odds)
    except (TypeError, ValueError):
        return ""
    lo, hi = GAMES_EXCLUDED_LINE_RANGE
    if lo <= line <= hi:
        return f"linie {lo:g}-{hi:g}"
    if odds > GAMES_MAX_ODDS:
        return f"cota > {GAMES_MAX_ODDS:.2f}"
    return ""


def blended_pct(comp: float, impl: float, confidence: float) -> float:
    """Estimarea folosita la selectie: piata + o parte mica din modelul
    nostru. Modelul primeste MODEL_WEIGHT (30%) din diferenta fata de piata,
    redus si el de increderea in rating (0.3 la incredere 0, 1.0 la maxima)."""
    weight = 0.3 + 0.7 * confidence
    return impl + MODEL_WEIGHT * weight * (comp - impl)


def filter_recommended_picks(
    df: pd.DataFrame,
    min_blend_edge_pp: float = MIN_BLEND_EDGE_PP,
    min_blend_pct: float = MIN_BLEND_PCT,
    max_odds: float = MAX_ODDS,
    max_edge_pp: float = MAX_EDGE_PP,
    max_composite_pct: float = MAX_COMPOSITE_PCT,
) -> pd.DataFrame:
    """Regulile din 2026-10-11 (vezi comentariul de la MODEL_WEIGHT). Un
    jucator e pick daca:
    - estimarea combinata (blended_pct) e cu >= min_blend_edge_pp peste
      cota implicita si >= min_blend_pct (il vedem castigator, nu outsider)
    - cota lui e <= max_odds
    - turneul nu e ITF/UTR (coloana "Tur"; daca lipseste, nu filtram)
    - edge-ul brut si estimarea modelului sunt sub plafoanele de date
      stricate (max_edge_pp / max_composite_pct, vezi list_suspect_picks)
    - exista o linie "Peste X game-uri" pe el (necesita --extended-odds)
    Adauga coloanele "_recommended_player" (1/2), "_edge_pp" (brut, model -
    piata), "_blend_pct", "_blend_edge_pp", "_comp_pct", "_rec_odds",
    "_games_line", "_games_odds". Sortat dupa _blend_edge_pp."""
    rows = []
    for _, row in df.iterrows():
        if str(row.get(_COL_TOUR, "")).strip().lower() in EXCLUDED_TOURS:
            continue
        confidence = row.get(_COL_RATING_CONF)
        # confidence lipsa (None/NaN) = tratam ca 0 -> pondere minima a modelului
        confidence = 0.0 if pd.isna(confidence) else float(confidence)
        for side, comp_col, impl_col, odds_col, line_col, games_col in (
            (1, _COL_COMP1, _COL_IMPL1, _COL_ODDS1, _COL_GAMES_LINE_P1, _COL_GAMES_ODDS_P1),
            (2, _COL_COMP2, _COL_IMPL2, _COL_ODDS2, _COL_GAMES_LINE_P2, _COL_GAMES_ODDS_P2),
        ):
            comp, impl, odds = row.get(comp_col), row.get(impl_col), row.get(odds_col)
            games_odds = row.get(games_col)
            if pd.isna(comp) or pd.isna(impl) or pd.isna(odds) or pd.isna(games_odds):
                continue
            blend = blended_pct(comp, impl, confidence)
            if (
                blend - impl >= min_blend_edge_pp
                and blend >= min_blend_pct
                and odds <= max_odds
                and comp - impl <= max_edge_pp
                and comp <= max_composite_pct
            ):
                new_row = row.copy()
                new_row["_recommended_player"] = side
                new_row["_edge_pp"] = comp - impl
                new_row["_blend_pct"] = blend
                new_row["_blend_edge_pp"] = blend - impl
                new_row["_comp_pct"] = comp
                new_row["_rec_odds"] = odds
                new_row["_games_line"] = row.get(line_col)
                new_row["_games_odds"] = games_odds
                rows.append(new_row)
                break

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("_blend_edge_pp", ascending=False)


def list_suspect_picks(df: pd.DataFrame) -> pd.DataFrame:
    """Meciurile unde modelul depaseste MAX_EDGE_PP fata de piata sau
    MAX_COMPOSITE_PCT pe un jucator - aproape sigur date gresite (jucatori
    inversati, rating lipsa etc.), de verificat manual, nu de pariat."""
    rows = []
    for _, row in df.iterrows():
        for side, comp_col, impl_col, odds_col in (
            (1, _COL_COMP1, _COL_IMPL1, _COL_ODDS1), (2, _COL_COMP2, _COL_IMPL2, _COL_ODDS2),
        ):
            comp, impl = row.get(comp_col), row.get(impl_col)
            if pd.isna(comp) or pd.isna(impl):
                continue
            if comp - impl > MAX_EDGE_PP or comp > MAX_COMPOSITE_PCT:
                new_row = row.copy()
                new_row["_recommended_player"] = side
                new_row["_edge_pp"] = comp - impl
                new_row["_comp_pct"] = comp
                new_row["_rec_odds"] = row.get(odds_col)
                rows.append(new_row)
                break
    return pd.DataFrame(rows)


def _clean(value) -> str:
    """Converteste NaN (celule goale la citirea din Excel) in string gol -
    spre deosebire de un simplu `x or ""`, NaN e truthy in Python (doar
    0.0 e falsy dintre float-uri), deci `nan or ""` intoarce tot nan."""
    if pd.isna(value):
        return ""
    return str(value)


# Rezultatul backtest-ului din 2026-09-23 (stats/backtest_report.md): 568 de
# meciuri jucate intre 8 si 21 sept. Pe exact filtrul din email (edge >= 15pp)
# au iesit 225 de pariuri, castigate 16% (piata estima 22%), ROI ~-37% la o
# marja de ~6%. De aceea pick-urile sunt marcate EXPERIMENTAL - continuam sa
# le logam in picks_log.csv ca test pe hartie, nu ca sfat de pariere.
EXPERIMENTAL_WARNING_HTML = (
    "<div style='margin:10px 0 16px 0; padding:12px; border:2px solid #b00; border-radius:6px; "
    "background:#fff3f3; color:#600;'>"
    "<b>EXPERIMENTAL — NU pariați pe baza acestor pick-uri.</b><br>"
    "Până pe 10 oct. modelul alegea mai ales outsideri: 172 de pick-uri, 35% câștigate, "
    "pe game-uri &minus;16 unități. De pe 11 oct. regulile sunt noi (favoriți, cotă &le; 2.00, fără ITF/UTR); "
    "pe istoric au ieșit între &minus;7% și +1% — nu sigur pe plus. "
    "Statistica regulilor noi apare separat la final.</div>"
)


def build_email_body(df: pd.DataFrame, date_str: str, underdog_html: str = "") -> str:
    picks = filter_recommended_picks(df)

    lines = []
    lines.append(f"<h2>Raport tenis (EXPERIMENTAL) — {date_str}</h2>")
    lines.append(EXPERIMENTAL_WARNING_HTML)
    lines.append(
        f"<p>Total meciuri analizate: <b>{len(df)}</b>. "
        f"Mai jos: doar pick-urile experimentale care trec de filtre (estimare combinata = piata + "
        f"{MODEL_WEIGHT:.0%} din model, cu &ge; {MIN_BLEND_EDGE_PP:.0f}pp peste piata si &ge; {MIN_BLEND_PCT:.0f}%, "
        f"cota &le; {MAX_ODDS:.2f}, fara ITF/UTR, cu o linie de total game-uri pe jucatorul recomandat), "
        f"sortate dupa avantajul combinat.</p>"
    )

    if picks.empty:
        lines.append("<p><i>Niciun meci nu a trecut de filtre azi.</i></p>")
    else:
        lines.append(f"<p><b>{len(picks)}</b> pick-uri experimentale:</p>")
        for _, row in picks.iterrows():
            p1, p2 = _clean(row.get(_COL_P1)), _clean(row.get(_COL_P2))
            odds1, odds2 = _clean(row.get(_COL_ODDS1)), _clean(row.get(_COL_ODDS2))
            comp1, comp2 = _clean(row.get(_COL_COMP1)), _clean(row.get(_COL_COMP2))
            implied1, implied2 = _clean(row.get(_COL_IMPL1)), _clean(row.get(_COL_IMPL2))
            tournament = _clean(row.get(_COL_TOURNAMENT))
            time_text = _clean(row.get(_COL_TIME))
            url = _clean(row.get(_COL_URL))

            rec_player = row["_recommended_player"]
            rec_name = p1 if rec_player == 1 else p2
            edge = row["_edge_pp"]
            rec_odds = row["_rec_odds"]
            comp_pct = row["_comp_pct"]
            blend_pct = row["_blend_pct"]
            games_line = row["_games_line"]
            games_odds = row["_games_odds"]

            lines.append("<div style='margin-bottom:16px; padding:10px; border:1px solid #ddd; border-radius:6px;'>")
            lines.append(f"<h3 style='margin:0 0 6px 0;'>{p1} vs {p2}</h3>")
            lines.append(f"<p style='margin:2px 0; color:#555;'>{tournament} — {time_text}</p>")
            excluded = games_exclusion_reason(games_line, games_odds)
            games_text = (
                f"<s>Peste {games_line} game-uri @ {games_odds}</s> EXCLUS ({excluded})"
                if excluded else f"Peste {games_line} game-uri @ {games_odds}"
            )
            lines.append(
                f"<p style='margin:6px 0;'><b>Pick experimental: {rec_name}</b> (cota {rec_odds}, estimare combinata "
                f"{blend_pct:.1f}%, model singur {comp_pct:.1f}% / +{edge:.0f}pp, {games_text})</p>"
            )
            lines.append(f"<p style='margin:6px 0;'><b>Cote Superbet:</b> {odds1} / {odds2} (implicit {implied1}% / {implied2}%)</p>")
            lines.append(f"<p style='margin:6px 0;'><b>Estimare noastra:</b> {comp1}% / {comp2}%</p>")
            if url:
                lines.append(f"<p style='margin:6px 0;'><a href='{url}'>Vezi pe Superbet.ro</a></p>")
            lines.append("</div>")

    suspects = list_suspect_picks(df)
    if not suspects.empty:
        lines.append(
            f"<h3 style='color:#b00;'>Suspecte - NU pariati ({len(suspects)})</h3>"
            f"<p>Edge peste {MAX_EDGE_PP:.0f}pp sau estimare peste {MAX_COMPOSITE_PCT:.0f}% - "
            f"aproape sigur o eroare de date. Excluse din recomandari si din picks_log.csv.</p><ul>"
        )
        for _, row in suspects.iterrows():
            p1, p2 = _clean(row.get(_COL_P1)), _clean(row.get(_COL_P2))
            rec_name = p1 if row["_recommended_player"] == 1 else p2
            lines.append(
                f"<li>{p1} vs {p2}: {rec_name} (cota {row['_rec_odds']}, edge +{row['_edge_pp']:.0f}pp, "
                f"estimare {row['_comp_pct']:.1f}%)</li>"
            )
        lines.append("</ul>")

    if underdog_html:
        lines.append(underdog_html)

    lines.append(
        "<p style='margin-top:20px; padding-top:10px; border-top:1px solid #ddd; color:#888; font-size:0.9em;'>"
        "Estimarea noastra e o combinatie simpla rank+formă recentă, nu un model validat statistic.</p>"
    )
    lines.append(accuracy_summary_html())
    lines.append(underdog_summary_html())

    return "\n".join(lines)


STATS_CSV_PATH = Path("stats") / "recommendation_stats.csv"


def log_daily_stats(df: pd.DataFrame, picks: pd.DataFrame, date_str: str) -> None:
    """Adauga un rand in stats/recommendation_stats.csv cu metrici zilnice
    (total meciuri, nr. recomandari, % recomandate, edge mediu, incredere
    medie), ca sa poti urmari in timp daca ponderarea prin incredere reduce
    volumul de recomandari constant sau variaza mult de la o zi la alta.
    Creeaza fisierul cu header daca nu exista inca. CONFIRMAT (2026-09-16,
    cu Andrei): rulat automat la fiecare trimitere de raport, ca sa nu
    trebuiasca notat manual."""
    STATS_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)

    total_matches = len(df)
    total_recommendations = len(picks)
    avg_edge = picks["_edge_pp"].mean() if not picks.empty else None
    avg_confidence = (
        picks[_COL_RATING_CONF].mean()
        if not picks.empty and _COL_RATING_CONF in picks.columns
        else None
    )

    row = {
        "date": date_str,
        "total_matches": total_matches,
        "total_recommendations": total_recommendations,
        "pct_recommended": round(100 * total_recommendations / total_matches, 1) if total_matches else None,
        "avg_edge_pp": round(avg_edge, 1) if avg_edge is not None else None,
        "avg_rating_confidence": round(avg_confidence, 2) if avg_confidence is not None else None,
    }

    file_exists = STATS_CSV_PATH.exists()
    with open(STATS_CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def log_todays_picks(picks: pd.DataFrame, date_str: str) -> None:
    """Adauga recomandarile de azi in stats/picks_log.csv, cu result="pending" -
    va fi completat de check_results.py, dupa ce meciurile se joaca.
    Acelasi tipar ca la proiectul SuperBet de fotbal (recommendations_log.csv
    de acolo). Nu duplica randuri daca se ruleaza de mai multe ori pentru
    aceeasi zi (verifica date+player1+player2)."""
    PICKS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if PICKS_LOG_PATH.exists():
        log = pd.read_csv(PICKS_LOG_PATH, dtype=str)
    else:
        log = pd.DataFrame(columns=PICKS_LOG_COLUMNS)

    new_rows = []
    for _, row in picks.iterrows():
        p1, p2 = row.get(_COL_P1, ""), row.get(_COL_P2, "")
        already_logged = ((log["date"] == date_str) & (log["player1"] == p1) & (log["player2"] == p2)).any()
        if already_logged:
            continue
        rec_player = row["_recommended_player"]
        recommended = p1 if rec_player == 1 else p2
        opponent = p2 if rec_player == 1 else p1
        new_rows.append({
            "date": date_str,
            "tournament": row.get(_COL_TOURNAMENT, ""),
            "player1": p1,
            "player2": p2,
            "recommended_player": recommended,
            "opponent": opponent,
            "edge_pp": row["_edge_pp"],
            "rec_odds": row["_rec_odds"],
            "comp_pct": row["_comp_pct"],
            "games_line": row["_games_line"],
            "games_odds": row["_games_odds"],
            "te_match_id": row.get(_COL_TE_MATCH_ID, ""),
            "result": "pending",
            "score": "",
            "checked_at": "",
            "set_scores": "",
            "rec_games": "",
            "games_result": "",
            "games_excluded": games_exclusion_reason(row["_games_line"], row["_games_odds"]),
            "blend_pct": round(row["_blend_pct"], 1),
            "rules": RULES_VERSION,
        })
    if new_rows:
        log = pd.concat([log, pd.DataFrame(new_rows)], ignore_index=True)
        log.to_csv(PICKS_LOG_PATH, index=False)


def _results_line(log: pd.DataFrame, label: str) -> str:
    """Rata de castig si profitul (miza 1) pe castigator si pe game-uri."""
    resolved = log[log["result"].isin(["won", "lost"])]
    if resolved.empty:
        return ""
    won = (resolved["result"] == "won").sum()
    text = (f"<b>{label}:</b> din {len(resolved)} pick-uri confirmate, {won} au fost castigate "
            f"({won / len(resolved):.0%}), profit {_profit_units(resolved, 'result', 'rec_odds'):+.2f} unitati la miza 1.")
    if "games_result" in log.columns:
        games = log[log["games_result"].isin(["won", "lost"])]
        if "games_excluded" in games.columns:
            games = games[games["games_excluded"].fillna("") == ""]
        if not games.empty:
            games_won = (games["games_result"] == "won").sum()
            text += (f"<br>&nbsp;&nbsp;Peste game-uri jucator: din {len(games)} confirmate, {games_won} castigate "
                     f"({games_won / len(games):.0%}), profit {_profit_units(games, 'games_result', 'games_odds'):+.2f} unitati.")
    return text


def accuracy_summary_html() -> str:
    """Rezumatul rezultatelor reale din picks_log.csv: separat pentru
    regulile curente (coloana "rules") si pentru tot istoricul. Gol daca
    inca n-avem nicio recomandare confirmata."""
    if not PICKS_LOG_PATH.exists():
        return ""
    log = pd.read_csv(PICKS_LOG_PATH, dtype=str)
    lines = []
    if "rules" in log.columns:
        current = log[log["rules"] == RULES_VERSION]
        lines.append(_results_line(current, "Reguli noi (de pe 11 oct.)")
                     or "<b>Reguli noi (de pe 11 oct.):</b> niciun pick confirmat inca.")
    lines.append(_results_line(log, "Tot istoricul (include regulile vechi)"))
    lines = [line for line in lines if line]
    if not lines or not log["result"].isin(["won", "lost"]).any():
        return ""
    return ("<p style='margin-top:20px; padding-top:10px; border-top:1px solid #ddd; color:#555;'>"
            "<b>Test pe hartie, pana acum.</b><br>" + "<br>".join(lines) + "</p>")


def underdog_summary_html() -> str:
    """Rezultatele de pana acum ale urmaririi pe hartie a outsiderilor
    (stats/underdog_games_log.csv), doar randurile care trec de filtru."""
    import underdog

    if not underdog.LOG_PATH.exists():
        return ""
    log = pd.read_csv(underdog.LOG_PATH, dtype=str)
    done = log[(log["filter_pass"] == "True") & log["games_result"].isin(["won", "lost"])]
    if done.empty:
        return ""
    rate = (done["games_result"] == "won").mean()
    return (
        "<p style='color:#555;'><b>Outsideri — game-uri, test pe hârtie:</b> "
        f"{len(done)} linii confirmate (toate liniile loggate ale jucătorilor care trec de filtru), "
        f"{(done['games_result'] == 'won').sum()} trecute ({rate:.0%}), "
        f"profit {_profit_units(done, 'games_result', 'games_odds'):+.2f} unitati la miza 1.</p>"
    )


def _profit_units(rows: pd.DataFrame, result_col: str, odds_col: str) -> float:
    """Profit la miza fixa de 1 unitate: +(cota-1) la castig, -1 la pierdere."""
    odds = pd.to_numeric(rows[odds_col], errors="coerce")
    won = rows[result_col] == "won"
    return float((odds - 1).where(won, -1).sum())


def list_high_edge_matches(df: pd.DataFrame, min_edge_pp: float = 25.0) -> pd.DataFrame:
    """Lista BRUTA (fara filtrul de cota si fara pragul de estimare
    compusa) cu toate meciurile unde edge-ul absolut (estimare -
    implicit) >= min_edge_pp, sortata descrescator dupa edge. Utila
    pentru inspectie rapida — raspunde la intrebarea "care meci are
    cele mai multe puncte pp" fara sa treaca prin restul filtrelor de
    recomandare (cota, estimare combinata, ITF/UTR). Nu se foloseste in
    email-ul zilnic, doar pentru debug/inspectie manuala."""
    rows = []
    for _, row in df.iterrows():
        comp1, comp2 = row.get(_COL_COMP1), row.get(_COL_COMP2)
        impl1, impl2 = row.get(_COL_IMPL1), row.get(_COL_IMPL2)
        if pd.isna(comp1) or pd.isna(impl1):
            continue
        edge1 = comp1 - impl1
        edge = edge1 if edge1 >= 0 else -edge1
        if edge >= min_edge_pp:
            new_row = row.copy()
            new_row["_recommended_player"] = 1 if edge1 >= 0 else 2
            new_row["_edge_pp"] = edge
            rows.append(new_row)
    if not rows:
        return pd.DataFrame()
    result = pd.DataFrame(rows)
    return result.sort_values("_edge_pp", ascending=False)


def print_high_edge_matches(df: pd.DataFrame, min_edge_pp: float = 25.0) -> None:
    matches = list_high_edge_matches(df, min_edge_pp)
    if matches.empty:
        print(f"Niciun meci cu edge >= {min_edge_pp:.0f}pp.")
        return
    print(f"{len(matches)} meciuri cu edge >= {min_edge_pp:.0f}pp:\n")
    for _, row in matches.iterrows():
        p1, p2 = _clean(row.get(_COL_P1)), _clean(row.get(_COL_P2))
        rec_player = row["_recommended_player"]
        rec_name = p1 if rec_player == 1 else p2
        odds = row.get(_COL_ODDS1) if rec_player == 1 else row.get(_COL_ODDS2)
        comp = row.get(_COL_COMP1) if rec_player == 1 else row.get(_COL_COMP2)
        print(
            f"  {row['_edge_pp']:5.1f}pp | {rec_name:<30} | cota {odds} | estimare {comp}% "
            f"| {p1} vs {p2} ({_clean(row.get(_COL_TIME))})"
        )


def build_high_edge_email_body(df: pd.DataFrame, date_str: str, min_edge_pp: float = 25.0) -> str:
    """Corpul HTML pentru email-ul cu meciurile de edge mare (brut, fara
    filtrul de cota/estimare compusa) — folosit de --list-high-edge."""
    matches = list_high_edge_matches(df, min_edge_pp)

    lines = []
    lines.append(f"<h2>Meciuri cu edge &ge; {min_edge_pp:.0f}pp (EXPERIMENTAL) — {date_str}</h2>")
    lines.append(EXPERIMENTAL_WARNING_HTML)
    lines.append(
        f"<p>Total meciuri analizate: <b>{len(df)}</b>. Lista de mai jos NU trece prin filtrele de "
        f"recomandare (cota, estimare combinata, ITF/UTR) — doar edge brut al modelului, "
        f"sortat descrescator.</p>"
    )

    if matches.empty:
        lines.append(f"<p><i>Niciun meci nu are edge &ge; {min_edge_pp:.0f}pp azi.</i></p>")
    else:
        lines.append(f"<p><b>{len(matches)}</b> meciuri:</p>")
        for _, row in matches.iterrows():
            p1, p2 = _clean(row.get(_COL_P1)), _clean(row.get(_COL_P2))
            odds1, odds2 = _clean(row.get(_COL_ODDS1)), _clean(row.get(_COL_ODDS2))
            comp1, comp2 = _clean(row.get(_COL_COMP1)), _clean(row.get(_COL_COMP2))
            implied1, implied2 = _clean(row.get(_COL_IMPL1)), _clean(row.get(_COL_IMPL2))
            tournament = _clean(row.get(_COL_TOURNAMENT))
            time_text = _clean(row.get(_COL_TIME))
            url = _clean(row.get(_COL_URL))

            rec_player = row["_recommended_player"]
            rec_name = p1 if rec_player == 1 else p2
            edge = row["_edge_pp"]
            rec_odds = odds1 if rec_player == 1 else odds2

            lines.append("<div style='margin-bottom:16px; padding:10px; border:1px solid #ddd; border-radius:6px;'>")
            lines.append(f"<h3 style='margin:0 0 6px 0;'>{p1} vs {p2}</h3>")
            lines.append(f"<p style='margin:2px 0; color:#555;'>{tournament} — {time_text}</p>")
            lines.append(
                f"<p style='margin:6px 0;'><b>Pick experimental: {rec_name}</b> (cota {rec_odds}, edge +{edge:.0f}pp fata de piata)</p>"
            )
            lines.append(f"<p style='margin:6px 0;'><b>Cote Superbet:</b> {odds1} / {odds2} (implicit {implied1}% / {implied2}%)</p>")
            lines.append(f"<p style='margin:6px 0;'><b>Estimare noastra:</b> {comp1}% / {comp2}%</p>")
            if url:
                lines.append(f"<p style='margin:6px 0;'><a href='{url}'>Vezi pe Superbet.ro</a></p>")
            lines.append("</div>")

    lines.append(
        "<p style='margin-top:20px; padding-top:10px; border-top:1px solid #ddd; color:#888; font-size:0.9em;'>"
        "Estimarea noastra e o combinatie simpla rank+formă recentă, nu un model validat statistic. "
        "Lista asta e neseletiva — poate include meciuri cu cota mica sau estimare sub 60% care nu ar "
        "trece de filtrul normal de recomandari.</p>"
    )

    return "\n".join(lines)


def _underdog_candidates(df: pd.DataFrame) -> pd.DataFrame | None:
    """Outsiderii zilei (vezi underdog.py). None daca istoricul
    (data/results.csv.gz, construit de history.py) lipseste."""
    import main

    if not underdog.history.RESULTS_CSV.exists():
        print("Fara data/results.csv.gz - sar peste sectiunea de outsideri.")
        return None
    return underdog.select_underdogs(df, underdog.build_history(), main._COLUMN_LABELS)


def send_email(subject: str, html_body: str) -> None:
    gmail_address = os.environ["GMAIL_ADDRESS"]
    gmail_app_password = os.environ["GMAIL_APP_PASSWORD"]
    email_to = os.environ.get("EMAIL_TO", gmail_address)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = email_to
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_address, gmail_app_password)
        server.sendmail(gmail_address, [email_to], msg.as_string())


def main() -> None:
    parser = argparse.ArgumentParser(description="Trimite raportul zilnic de tenis pe email.")
    parser.add_argument("--xlsx", required=True, help="Calea catre fisierul Excel generat de main.py")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD, folosit in subiect/titlu")
    parser.add_argument("--dry-run", action="store_true", help="Afiseaza email-ul in loc sa-l trimita")
    parser.add_argument(
        "--list-high-edge",
        type=float,
        nargs="?",
        const=25.0,
        default=None,
        metavar="MIN_EDGE_PP",
        help="In loc de email, listeaza toate meciurile cu edge brut >= pragul dat (implicit 25pp), fara filtrul de cota/estimare compusa",
    )
    args = parser.parse_args()

    df = pd.read_excel(args.xlsx, sheet_name="Tenis")

    if args.list_high_edge is not None:
        subject = f"Edge mare ({args.list_high_edge:.0f}pp+) — {args.date}"
        body = build_high_edge_email_body(df, args.date, args.list_high_edge)
        if args.dry_run:
            print(subject)
            print(body)
            return
        send_email(subject, body)
        print(f"Email trimis: {subject}")
        return

    picks = filter_recommended_picks(df)
    log_daily_stats(df, picks, args.date)
    underdogs = _underdog_candidates(df)
    underdog_html = underdog.email_section_html(underdogs) if underdogs is not None else ""
    body = build_email_body(df, args.date, underdog_html)
    subject = f"Raport tenis EXPERIMENTAL ({len(df)} meciuri) — {args.date}"

    if args.dry_run:
        print(subject)
        print(body)
        return

    if df.empty:
        print("Niciun meci in raport azi — sar peste trimiterea email-ului.")
        return

    log_todays_picks(picks, args.date)
    if underdogs is not None:
        underdog.log_underdogs(underdogs, args.date)
    send_email(subject, body)
    print(f"Email trimis: {subject}")


if __name__ == "__main__":
    main()
