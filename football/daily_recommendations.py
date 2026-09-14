"""Daily recommendation email: cross-references BetExplorer's "100% Over
2.5" hit-rate data (both teams went Over 2.5 in every game of their
season so far) against SuperBet's own daily match list (live odds,
confirms the match is actually available to bet on) -- matched by team
name -- and emails the result.

Expects two already-generated Excel files (produced by running each
project's own main.py --with-stats / --all beforehand -- see the GitHub
Actions workflow for the exact commands):
  --bet-xlsx     path to BetExplorer's output/matches.xlsx
  --superbet-xlsx path to SuperBet's output/matches.xlsx

IMPORTANT: both export.py modules write the DESCRIPTIVE labels as the
actual Excel header row (see _COLUMN_LABELS in each betscraper/export.py
and superbet_scraper/export.py) -- e.g. "Home Team", not "home_team". So
pd.read_excel() sees those labels as column names, not the internal keys.
Several labels are shared between both sheets (League, Home Team, Away
Team, Odds Over, Match Link), so after merging they get suffixed
" (BetExplorer)" / " (Superbet)".

Email credentials come from environment variables (set as GitHub Secrets
in the workflow, never committed):
  GMAIL_ADDRESS       the sending Gmail account
  GMAIL_APP_PASSWORD  a Gmail "App Password" (NOT the regular account
                       password -- see README for how to generate one)
  EMAIL_TO            recipient address (can be the same as GMAIL_ADDRESS)
"""
from __future__ import annotations

import argparse
import os
import smtplib
import sys
import unicodedata
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pandas as pd

_SUFFIX_BET = " (BetExplorer)"
_SUFFIX_SB = " (Superbet)"


def normalize_name(name: str) -> str:
    """Lowercase, strip accents/punctuation, collapse whitespace -- so
    "AS Roma" and "As Roma" (or accented variants) match reliably across
    the two sources, which don't necessarily use identical team-name
    formatting.
    """
    if not isinstance(name, str):
        return ""
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().strip()
    normalized = "".join(c if c.isalnum() or c.isspace() else " " for c in normalized)
    return " ".join(normalized.split())


def load_high_confidence(bet_xlsx: str) -> pd.DataFrame:
    df = pd.read_excel(bet_xlsx, sheet_name="100% Over 2.5")
    df["_home_norm"] = df["Home Team"].map(normalize_name)
    df["_away_norm"] = df["Away Team"].map(normalize_name)
    return df


def load_superbet_matches(superbet_xlsx: str) -> pd.DataFrame:
    df = pd.read_excel(superbet_xlsx, sheet_name="Matches")
    df["_home_norm"] = df["Home Team"].map(normalize_name)
    df["_away_norm"] = df["Away Team"].map(normalize_name)
    return df


def match_across_sources(high_confidence: pd.DataFrame, superbet: pd.DataFrame) -> pd.DataFrame:
    """Inner-join on normalized (home, away) team names. A match present in
    BetExplorer's 100%-confidence list but NOT found here simply isn't
    (yet, or ever) offered on Superbet for this date/run -- that's a normal
    outcome, not an error, and is reported separately in the email rather
    than silently dropped.

    Both sheets share several column names (League, Home Team, Away Team,
    Odds Over, Match Link) -- pandas suffixes those on merge so we can
    pick the right source per field afterwards (live odds/link from
    Superbet, historical hit-rate counts from BetExplorer).
    """
    merged = high_confidence.merge(
        superbet,
        on=["_home_norm", "_away_norm"],
        how="inner",
        suffixes=(_SUFFIX_BET, _SUFFIX_SB),
    )
    return merged


def build_email_body(matched: pd.DataFrame, unmatched_count: int, date_str: str) -> str:
    lines = []
    lines.append(f"<h2>Recomandari zilnice -- {date_str}</h2>")
    lines.append(
        "<p>Meciuri unde <b>ambele echipe</b> au avut Peste 2.5 goluri (3+ goluri) "
        "in <b>fiecare</b> meci din sezonul curent (conform BetExplorer), "
        "si sunt disponibile de pariat pe Superbet.ro chiar acum.</p>"
    )

    if matched.empty:
        lines.append("<p><i>Niciun meci nu s-a potrivit intre cele doua surse azi.</i></p>")
    else:
        for _, row in matched.iterrows():
            league = row.get("League" + _SUFFIX_BET, row.get("League", ""))
            home = row.get("Home Team" + _SUFFIX_BET, row.get("Home Team", ""))
            away = row.get("Away Team" + _SUFFIX_BET, row.get("Away Team", ""))
            time_text = row.get("Kick-off Time" + _SUFFIX_BET, row.get("Kick-off Time", ""))
            odds_over = row.get("Odds Over" + _SUFFIX_SB, row.get("Odds Over", ""))
            home_over = row.get("Home Over 2.5 (matches)")
            home_under = row.get("Home Under 2.5 (matches)")
            away_over = row.get("Away Over 2.5 (matches)")
            away_under = row.get("Away Under 2.5 (matches)")
            match_url = row.get("Match Link" + _SUFFIX_SB) or row.get("Match Link" + _SUFFIX_BET) or row.get("Match Link")

            lines.append("<div style='margin-bottom:18px; padding:10px; border:1px solid #ddd; border-radius:6px;'>")
            lines.append(f"<h3 style='margin:0 0 6px 0;'>{home} vs {away}</h3>")
            lines.append(f"<p style='margin:2px 0; color:#555;'>{league} -- {time_text}</p>")
            lines.append(
                f"<p style='margin:6px 0;'><b>Istoric (BetExplorer):</b> "
                f"{home} Peste 2.5 in {home_over}/{int(home_over or 0) + int(home_under or 0)} meciuri; "
                f"{away} Peste 2.5 in {away_over}/{int(away_over or 0) + int(away_under or 0)} meciuri.</p>"
            )
            lines.append(f"<p style='margin:6px 0;'><b>Cota Peste 2.5 (Superbet):</b> {odds_over}</p>")
            if match_url:
                lines.append(f"<p style='margin:6px 0;'><a href='{match_url}'>Vezi pe Superbet.ro</a></p>")
            lines.append("</div>")

    if unmatched_count:
        lines.append(
            f"<p style='color:#888; font-size:0.9em;'>Nota: inca {unmatched_count} meciuri au istoric 100% "
            "conform BetExplorer, dar nu au fost gasite (inca) pe Superbet.ro azi.</p>"
        )

    return "\n".join(lines)


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
    parser = argparse.ArgumentParser(description="Build and send the daily 100%-confidence recommendation email.")
    parser.add_argument("--bet-xlsx", required=True, help="Path to BetExplorer's output/matches.xlsx")
    parser.add_argument("--superbet-xlsx", required=True, help="Path to SuperBet's output/matches.xlsx")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD, used in the email subject/heading")
    parser.add_argument("--dry-run", action="store_true", help="Print the email instead of sending it")
    args = parser.parse_args()

    high_confidence = load_high_confidence(args.bet_xlsx)
    superbet = load_superbet_matches(args.superbet_xlsx)
    matched = match_across_sources(high_confidence, superbet)

    unmatched_count = len(high_confidence) - len(matched)
    body = build_email_body(matched, unmatched_count, args.date)
    subject = f"Recomandari zilnice ({len(matched)} meciuri) -- {args.date}"

    if args.dry_run:
        print(subject)
        print(body)
        return

    if matched.empty and unmatched_count == 0:
        print("No high-confidence matches at all today -- skipping email.")
        return

    send_email(subject, body)
    print(f"Email sent: {subject}")


if __name__ == "__main__":
    main()
