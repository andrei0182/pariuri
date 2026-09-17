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
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

LOG_PATH = "recommendations_log.csv"
LOG_COLUMNS = [
    "date", "league", "home_team", "away_team", "odds_over",
    "kickoff_local", "result", "total_goals", "checked_at",
]

_SUFFIX_BET = " (BetExplorer)"
_SUFFIX_SB = " (Superbet)"
_LOCAL_TZ = ZoneInfo("Europe/Bucharest")


def to_local_kickoff(raw) -> str:
    """Both BetExplorer and Superbet store the kickoff time in UTC (CONFIRMED
    2026-09-14 via diagnose_times.py: BetExplorer's "17:00" matches
    Superbet's raw "2026-09-14 17:00:00" exactly, while the Superbet app
    itself displays that same match at 20:00 local). Superbet is the only
    one of the two that exports a full date+time (BetExplorer only exports
    a bare "HH:MM"), so it is the only one this can convert unambiguously.
    Uses zoneinfo (not a fixed +3h offset) so this stays correct across the
    October/March DST changes, not just for today.
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return ""
    try:
        parsed = pd.to_datetime(raw, utc=True)
    except (ValueError, TypeError):
        return str(raw)
    return parsed.tz_convert(_LOCAL_TZ).strftime("%H:%M")


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
    df["_kickoff_local"] = df["Kick-off Time"].map(to_local_kickoff)
    return df


def _names_match(name_a: str, name_b: str) -> bool:
    """Two normalized team names are considered the same team if every word
    of the SHORTER one appears in the LONGER one -- handles BetExplorer and
    Superbet formatting the same club differently, e.g. "torino" vs
    "torino fc", "blackburn u21" vs "blackburn rovers u21". Exact match is
    just the common case of this (identical word sets both ways).
    """
    if not name_a or not name_b:
        return False
    if name_a == name_b:
        return True
    tokens_a, tokens_b = set(name_a.split()), set(name_b.split())
    if not tokens_a or not tokens_b:
        return False
    return tokens_a <= tokens_b or tokens_b <= tokens_a


def match_across_sources(high_confidence: pd.DataFrame, superbet: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Fuzzy match on normalized (home, away) team names -- see
    _names_match. A BetExplorer match with no fuzzy match on Superbet
    simply isn't (yet, or ever) offered there for this date/run -- that's
    a normal outcome, not an error, and is reported separately in the
    email rather than silently dropped.

    Both sheets can share column names (League, Home Team, Odds Over,
    Match Link, ...) so every field is explicitly suffixed here (not left
    to pandas' merge-suffix mechanism) to keep the source unambiguous --
    live odds/link come from Superbet, historical hit-rate counts from
    BetExplorer.
    """
    matched_rows = []
    unmatched_names = []
    for _, bet_row in high_confidence.iterrows():
        candidates = superbet[
            superbet.apply(
                lambda sb_row: _names_match(bet_row["_home_norm"], sb_row["_home_norm"])
                and _names_match(bet_row["_away_norm"], sb_row["_away_norm"]),
                axis=1,
            )
        ]
        if candidates.empty:
            unmatched_names.append(f"{bet_row['Home Team']} vs {bet_row['Away Team']} ({bet_row['League']})")
            continue
        sb_row = candidates.iloc[0]
        combined = {}
        for col, val in bet_row.items():
            if col in ("_home_norm", "_away_norm"):
                continue
            combined[col + _SUFFIX_BET] = val
        for col, val in sb_row.items():
            if col in ("_home_norm", "_away_norm"):
                continue
            combined[col + _SUFFIX_SB] = val
        matched_rows.append(combined)
    matched_df = pd.DataFrame(matched_rows) if matched_rows else pd.DataFrame()
    return matched_df, unmatched_names

    


def log_todays_picks(matched: pd.DataFrame, date_str: str) -> None:
    """Appends today's matched picks to the persistent results log."""
    path = Path(LOG_PATH)
    if path.exists():
        log = pd.read_csv(path, dtype=str)
    else:
        log = pd.DataFrame(columns=LOG_COLUMNS)

    new_rows = []
    for _, row in matched.iterrows():
        home = row.get("Home Team" + _SUFFIX_BET, "")
        away = row.get("Away Team" + _SUFFIX_BET, "")
        already_logged = ((log["date"] == date_str) & (log["home_team"] == home) & (log["away_team"] == away)).any()
        if already_logged:
            continue
        new_rows.append({
            "date": date_str,
            "league": row.get("League" + _SUFFIX_BET, ""),
            "home_team": home,
            "away_team": away,
            "odds_over": row.get("Odds Over" + _SUFFIX_SB, ""),
            "kickoff_local": row.get("_kickoff_local" + _SUFFIX_SB, ""),
            "result": "pending",
            "total_goals": "",
            "checked_at": "",
        })
    if new_rows:
        log = pd.concat([log, pd.DataFrame(new_rows)], ignore_index=True)
        log.to_csv(path, index=False)


def accuracy_summary_html() -> str:
    path = Path(LOG_PATH)
    if not path.exists():
        return ""
    log = pd.read_csv(path, dtype=str)
    resolved = log[log["result"].isin(["over", "under"])]
    if resolved.empty:
        return ""
    hit_rate = (resolved["result"] == "over").mean()
    return (
        f"<p style='margin-top:20px; padding-top:10px; border-top:1px solid #ddd; color:#555;'>"
        f"<b>Statistica reala pana acum:</b> din {len(resolved)} recomandari confirmate, "
        f"{(resolved['result'] == 'over').sum()} au fost Peste 2.5 ({hit_rate:.0%}).</p>"
    )


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
            league = row.get("League" + _SUFFIX_BET, "")
            home = row.get("Home Team" + _SUFFIX_BET, "")
            away = row.get("Away Team" + _SUFFIX_BET, "")
            time_text = row.get("_kickoff_local" + _SUFFIX_SB, "") + " (ora Romaniei)"
            odds_over = row.get("Odds Over" + _SUFFIX_SB, "")
            home_over = row.get("Home Over 2.5 (matches)" + _SUFFIX_BET)
            home_under = row.get("Home Under 2.5 (matches)" + _SUFFIX_BET)
            away_over = row.get("Away Over 2.5 (matches)" + _SUFFIX_BET)
            away_under = row.get("Away Under 2.5 (matches)" + _SUFFIX_BET)
            match_url = row.get("Match Link" + _SUFFIX_SB) or row.get("Match Link" + _SUFFIX_BET)

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

    lines.append(accuracy_summary_html())

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
    matched, unmatched_names = match_across_sources(high_confidence, superbet)

    unmatched_count = len(unmatched_names)
    if unmatched_names:
        print("Meciuri BetExplorer nepotrivite pe Superbet:")
        for name in unmatched_names:
            print(f"  - {name}")

    body = build_email_body(matched, unmatched_count, args.date)
    subject = f"Recomandari zilnice ({len(matched)} meciuri) -- {args.date}"

    if args.dry_run:
        print(subject)
        print(body)
        return

    log_todays_picks(matched, args.date)

    if matched.empty and unmatched_count == 0:
        print("No high-confidence matches at all today -- skipping email.")
        return

    send_email(subject, body)
    print(f"Email sent: {subject}")


if __name__ == "__main__":
    main()
