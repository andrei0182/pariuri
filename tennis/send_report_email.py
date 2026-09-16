"""Trimite raportul zilnic de tenis pe email — atasat ca Excel, plus un
rezumat HTML in corpul mesajului cu meciurile unde estimarea noastra
difera semnificativ de piata ("Semnal" incepe cu "Posibil value").

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


def build_email_body(df: pd.DataFrame, date_str: str) -> str:
    picks = df[df["Semnal (estimare vs piață)"].astype(str).str.startswith("Posibil value")]

    lines = []
    lines.append(f"<h2>Raport tenis — {date_str}</h2>")
    lines.append(f"<p>Total meciuri analizate: <b>{len(df)}</b>. Fisierul complet e atasat.</p>")

    if picks.empty:
        lines.append("<p><i>Niciun meci cu semnal de \"value\" fata de piata azi.</i></p>")
    else:
        lines.append(f"<p>Meciuri unde estimarea noastra (rank+formă) difera semnificativ de cota Superbet ({len(picks)}):</p>")
        for _, row in picks.iterrows():
            p1, p2 = row.get("Jucător 1", ""), row.get("Jucător 2", "")
            odds1, odds2 = row.get("Cotă 1", ""), row.get("Cotă 2", "")
            signal = row.get("Semnal (estimare vs piață)", "")
            comp1, comp2 = row.get("% Estimare Compusă J1 (rank+formă)", ""), row.get("% Estimare Compusă J2 (rank+formă)", "")
            implied1, implied2 = row.get("% Implicit Cotă J1", ""), row.get("% Implicit Cotă J2", "")
            tournament = row.get("Turneu", "") or ""
            time_text = row.get("Ora", "") or ""
            url = row.get("Link Superbet", "")

            lines.append("<div style='margin-bottom:16px; padding:10px; border:1px solid #ddd; border-radius:6px;'>")
            lines.append(f"<h3 style='margin:0 0 6px 0;'>{p1} vs {p2}</h3>")
            lines.append(f"<p style='margin:2px 0; color:#555;'>{tournament} — {time_text}</p>")
            lines.append(f"<p style='margin:6px 0;'><b>Cote Superbet:</b> {odds1} / {odds2} (implicit {implied1}% / {implied2}%)</p>")
            lines.append(f"<p style='margin:6px 0;'><b>Estimare noastra:</b> {comp1}% / {comp2}%</p>")
            lines.append(f"<p style='margin:6px 0;'><b>Semnal:</b> {signal}</p>")
            if url:
                lines.append(f"<p style='margin:6px 0;'><a href='{url}'>Vezi pe Superbet.ro</a></p>")
            lines.append("</div>")

    lines.append(
        "<p style='margin-top:20px; padding-top:10px; border-top:1px solid #ddd; color:#888; font-size:0.9em;'>"
        "Estimarea noastra e o combinatie simpla rank+formă recentă, nu un model validat statistic — "
        "vezi fisierul atasat pentru toate detaliile (H2H, comparatie suprafata, formă pe meci-cu-meci).</p>"
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
