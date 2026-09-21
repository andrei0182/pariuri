"""Checks recommendations_log.csv for past picks still marked "pending" and
fills in what actually happened, by re-scraping BetExplorer's completed-
results page for each pending pick's date and reading the real final score.

Run BEFORE generating today's new recommendations (see the GitHub Actions
workflow) so the email's running accuracy summary is up to date. Safe to
run multiple times -- already-resolved rows are skipped, and a match not
found/not yet played is simply left "pending" for next time.

Reuses the betexplorer scraper that lives alongside this script in
football/ (scrape_betexplorer.py), since both are part of the same
monorepo checkout now -- no cross-repo checkout needed.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import unicodedata
from datetime import date as Date
from pathlib import Path

import pandas as pd

LOG_PATH = "recommendations_log.csv"
LOG_COLUMNS = [
    "date", "league", "home_team", "away_team", "odds_over",
    "home_matches", "away_matches",
    "kickoff_local", "result", "total_goals", "checked_at",
]


def normalize_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().strip()
    normalized = "".join(c if c.isalnum() or c.isspace() else " " for c in normalized)
    return " ".join(normalized.split())


def names_match(name_a: str, name_b: str) -> bool:
    if not name_a or not name_b:
        return False
    if name_a == name_b:
        return True
    tokens_a, tokens_b = set(name_a.split()), set(name_b.split())
    if not tokens_a or not tokens_b:
        return False
    return tokens_a <= tokens_b or tokens_b <= tokens_a


def load_log() -> pd.DataFrame:
    path = Path(LOG_PATH)
    if not path.exists():
        return pd.DataFrame(columns=LOG_COLUMNS)
    return pd.read_csv(path, dtype=str)


def save_log(df: pd.DataFrame) -> None:
    df.to_csv(LOG_PATH, index=False)


def scrape_bet_date(date_str: str, bet_repo: str) -> pd.DataFrame | None:
    out_path = f"/tmp/results_check_{date_str}.xlsx"
    cmd = [sys.executable, "scrape_betexplorer.py", "--date", date_str, "--output", out_path]
    result = subprocess.run(cmd, cwd=bet_repo, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  WARNING: bet scraper failed for {date_str}: {result.stderr.strip()[-500:]}")
        return None
    if not Path(out_path).exists():
        print(f"  WARNING: bet scraper produced no output file for {date_str}.")
        return None
    return pd.read_excel(out_path, sheet_name="Matches")


def resolve_pick(row: pd.Series, day_matches: pd.DataFrame) -> tuple[str, str]:
    home_norm = normalize_name(row["home_team"])
    away_norm = normalize_name(row["away_team"])
    for _, m in day_matches.iterrows():
        if names_match(home_norm, normalize_name(m["Home Team"])) and names_match(away_norm, normalize_name(m["Away Team"])):
            score = m.get("Final Score")
            if not isinstance(score, str) or ":" not in score:
                if isinstance(score, str) and score.strip().upper().startswith("POSTP"):
                    return "postponed", ""
                return "no_data", ""
            try:
                home_goals, away_goals = (int(x) for x in score.split(":", 1))
            except ValueError:
                return "no_data", ""
            total = home_goals + away_goals
            return ("over" if total > 2.5 else "under"), str(total)
    return "no_data", ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bet-repo", default=".", help="Directory containing scrape_betexplorer.py (defaults to the current directory, football/).")
    args = parser.parse_args()

    log = load_log()
    if log.empty:
        print("No log yet (recommendations_log.csv doesn't exist or is empty) -- nothing to check.")
        return

    today_str = Date.today().isoformat()
    pending = log[(log["result"] == "pending") & (log["date"] < today_str)]
    if pending.empty:
        print("No past-dated pending picks to check.")
        return

    pending_dates = sorted(pending["date"].unique())
    print(f"Checking {len(pending)} pending pick(s) across {len(pending_dates)} date(s): {pending_dates}")

    for date_str in pending_dates:
        print(f"Scraping BetExplorer results for {date_str}...")
        day_matches = scrape_bet_date(date_str, args.bet_repo)
        if day_matches is None:
            continue
        idxs = log.index[(log["result"] == "pending") & (log["date"] == date_str)]
        for idx in idxs:
            result, total_goals = resolve_pick(log.loc[idx], day_matches)
            if result == "no_data":
                continue
            log.loc[idx, "result"] = result
            log.loc[idx, "total_goals"] = total_goals
            log.loc[idx, "checked_at"] = Date.today().isoformat()
            print(f"  {log.loc[idx, 'home_team']} vs {log.loc[idx, 'away_team']} ({date_str}): {result} ({total_goals} goals)")

    save_log(log)
    resolved = log[log["result"].isin(["over", "under"])]
    if not resolved.empty:
        hit_rate = (resolved["result"] == "over").mean()
        print(f"\nOverall so far: {len(resolved)} confirmed picks, {hit_rate:.0%} went Over 2.5.")


if __name__ == "__main__":
    main()
