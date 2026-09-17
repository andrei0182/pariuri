"""Trimite raportul zilnic de tenis pe email — atasat ca Excel, plus un
rezumat HTML in corpul mesajului cu DOAR meciurile care trec de filtrele
de mai jos (nu toata lista, la fel ca la proiectul SuperBet care filtra
pe "100% Over 2.5" istoric).

Filtre aplicate (praguri alese cu Andrei, 2026-09-16):
  - diferenta (edge) intre estimarea noastra (rank+formă) si cota
    implicita Superbet >= MIN_EDGE_PP puncte procentuale
  - cota Superbet a partii recomandate >= MIN_ODDS (evitam favoriti
    zdrobitori unde diferenta e nesemnificativa practic)
  - fara limita maxima de cota (underdogi extremi raman inclusi)
  - toate categoriile de turnee raman incluse (UTR/ITF nu sunt excluse)

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
import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import pandas as pd

MIN_EDGE_PP = 15.0
MIN_ODDS = 1.3

_COL_P1, _COL_P2 = "Jucător 1", "Jucător 2"
_COL_ODDS1, _COL_ODDS2 = "Cotă 1", "Cotă 2"
_COL_COMP1, _COL_COMP2 = "% Estimare Compusă J1 (rank+formă+rating)", "% Estimare Compusă J2 (rank+formă+rating)"
_COL_IMPL1, _COL_IMPL2 = "% Implicit Cotă J1", "% Implicit Cotă J2"
_COL_RATING_CONF = "Încredere rating carieră (0-1)"
_COL_TOURNAMENT, _COL_TIME, _COL_URL = "Turneu", "Ora", "Link Superbet"


def filter_recommended_picks(df: pd.DataFrame, min_edge_pp: float = MIN_EDGE_PP, min_odds: float = MIN_ODDS) -> pd.DataFrame:
    """Pentru fiecare meci, calculeaza edge-ul (estimare - implicit) pe
    fiecare parte si pastreaza doar meciurile unde partea cu edge pozitiv
    mare (>= min_edge_pp, dupa ponderarea cu incredere) are si o cota
    Superbet >= min_odds. Edge-ul e ponderat de "Încredere rating carieră"
    (0-1): meciurile cu incredere mica (jucatori cu putine meciuri
    disponibile pentru rating-ul de cariera) au nevoie de un edge brut mai
    mare ca sa treaca de filtru, ceea ce reduce volumul de recomandari
    fara sa scada pragul de baza. CONFIRMAT (2026-09-16, cu Andrei): asta
    e raspunsul la problema initiala - prea multe meciuri treceau de
    filtrul simplu pe edge brut.
    Adauga coloane noi: "_recommended_player" (1 sau 2), "_edge_pp" (brut),
    "_edge_pp_weighted" (dupa ponderare, folosit pentru sortare), "_rec_odds"."""
    rows = []
    for _, row in df.iterrows():
        comp1, comp2 = row.get(_COL_COMP1), row.get(_COL_COMP2)
        impl1, impl2 = row.get(_COL_IMPL1), row.get(_COL_IMPL2)
        odds1, odds2 = row.get(_COL_ODDS1), row.get(_COL_ODDS2)
        confidence = row.get(_COL_RATING_CONF)
        if pd.isna(comp1) or pd.isna(impl1):
            continue

        # confidence lipsa (None/NaN) = tratam ca 0 -> ponderare minima (0.3x)
        confidence = 0.0 if pd.isna(confidence) else float(confidence)
        # factor intre 0.3 (incredere 0) si 1.0 (incredere maxima) - un edge
        # "orb" (fara date de rating) trebuie sa fie de ~3.3x mai mare ca sa
        # treaca de acelasi prag decat unul cu incredere maxima. CONFIRMAT
        # (2026-09-16, cu Andrei): testat pe 31 de meciuri reale, reduce
        # recomandarile de la 13 la 9 (~30%) fata de filtrul pe edge brut,
        # fara sa excluda complet meciurile cu incredere 0 (spre deosebire
        # de o formula 0.0+1.0*incredere, care ar exclude orice meci cu
        # incredere 0 indiferent cat de puternic ar fi restul semnalelor).
        weight = 0.3 + 0.7 * confidence

        edge1 = comp1 - impl1  # pozitiv = value pe J1, negativ = value pe J2
        edge1_weighted = edge1 * weight

        if edge1_weighted >= min_edge_pp and not pd.isna(odds1) and odds1 >= min_odds:
            new_row = row.copy()
            new_row["_recommended_player"] = 1
            new_row["_edge_pp"] = edge1
            new_row["_edge_pp_weighted"] = edge1_weighted
            new_row["_rec_odds"] = odds1
            rows.append(new_row)
        elif -edge1_weighted >= min_edge_pp and not pd.isna(odds2) and odds2 >= min_odds:
            new_row = row.copy()
            new_row["_recommended_player"] = 2
            new_row["_edge_pp"] = -edge1
            new_row["_edge_pp_weighted"] = -edge1_weighted
            new_row["_rec_odds"] = odds2
            rows.append(new_row)

    if not rows:
        return pd.DataFrame()
    result = pd.DataFrame(rows)
    return result.sort_values("_edge_pp_weighted", ascending=False)


def _clean(value) -> str:
    """Converteste NaN (celule goale la citirea din Excel) in string gol -
    spre deosebire de un simplu `x or ""`, NaN e truthy in Python (doar
    0.0 e falsy dintre float-uri), deci `nan or ""` intoarce tot nan."""
    if pd.isna(value):
        return ""
    return str(value)


def build_email_body(df: pd.DataFrame, date_str: str) -> str:
    picks = filter_recommended_picks(df)

    lines = []
    lines.append(f"<h2>Raport tenis — {date_str}</h2>")
    lines.append(
        f"<p>Total meciuri analizate: <b>{len(df)}</b>. Fisierul complet cu toate meciurile e atasat. "
        f"Mai jos: doar recomandarile care trec de filtre (edge &ge; {MIN_EDGE_PP:.0f}pp fata de piata, "
        f"cota &ge; {MIN_ODDS:.1f}).</p>"
    )

    if picks.empty:
        lines.append("<p><i>Niciun meci nu a trecut de filtre azi.</i></p>")
    else:
        lines.append(f"<p><b>{len(picks)}</b> recomandari:</p>")
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

            lines.append("<div style='margin-bottom:16px; padding:10px; border:1px solid #ddd; border-radius:6px;'>")
            lines.append(f"<h3 style='margin:0 0 6px 0;'>{p1} vs {p2}</h3>")
            lines.append(f"<p style='margin:2px 0; color:#555;'>{tournament} — {time_text}</p>")
            lines.append(
                f"<p style='margin:6px 0;'><b>Recomandare: {rec_name}</b> (cota {rec_odds}, edge +{edge:.0f}pp fata de piata)</p>"
            )
            lines.append(f"<p style='margin:6px 0;'><b>Cote Superbet:</b> {odds1} / {odds2} (implicit {implied1}% / {implied2}%)</p>")
            lines.append(f"<p style='margin:6px 0;'><b>Estimare noastra:</b> {comp1}% / {comp2}%</p>")
            if url:
                lines.append(f"<p style='margin:6px 0;'><a href='{url}'>Vezi pe Superbet.ro</a></p>")
            lines.append("</div>")

    lines.append(
        "<p style='margin-top:20px; padding-top:10px; border-top:1px solid #ddd; color:#888; font-size:0.9em;'>"
        "Estimarea noastra e o combinatie simpla rank+formă recentă, nu un model validat statistic — "
        "vezi fisierul atasat pentru toate detaliile (H2H, comparatie suprafata, formă pe meci-cu-meci, "
        "toate meciurile inclusiv cele care nu au trecut de filtre).</p>"
    )

    return "\n".join(lines)


def send_email(subject: str, html_body: str, attachment_path: str) -> None:
    gmail_address = os.environ["GMAIL_ADDRESS"]
    gmail_app_password = os.environ["GMAIL_APP_PASSWORD"]
    email_to = os.environ.get("EMAIL_TO", gmail_address)

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = email_to

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt)

    path = Path(attachment_path)
    if path.exists():
        with open(path, "rb") as f:
            part = MIMEApplication(f.read(), Name=path.name)
        part["Content-Disposition"] = f'attachment; filename="{path.name}"'
        msg.attach(part)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_address, gmail_app_password)
        server.sendmail(gmail_address, [email_to], msg.as_string())


def main() -> None:
    parser = argparse.ArgumentParser(description="Trimite raportul zilnic de tenis pe email.")
    parser.add_argument("--xlsx", required=True, help="Calea catre fisierul Excel generat de main.py")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD, folosit in subiect/titlu")
    parser.add_argument("--dry-run", action="store_true", help="Afiseaza email-ul in loc sa-l trimita")
    args = parser.parse_args()

    df = pd.read_excel(args.xlsx, sheet_name="Tenis")
    body = build_email_body(df, args.date)
    subject = f"Raport tenis ({len(df)} meciuri) — {args.date}"

    if args.dry_run:
        print(subject)
        print(body)
        return

    if df.empty:
        print("Niciun meci in raport azi — sar peste trimiterea email-ului.")
        return

    send_email(subject, body, args.xlsx)
    print(f"Email trimis: {subject}")


if __name__ == "__main__":
    main()
