from __future__ import annotations

import argparse
import datetime as dt
import logging
import time

from betscraper.driver import build_driver
from betscraper.export import save_to_excel
from betscraper.match_list import scrape_day
from betscraper.match_stats import scrape_match_stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape BetExplorer matches, odds, and stats.")
    parser.add_argument(
        "--date",
        default=dt.date.today().isoformat(),
        help="Date to scrape, YYYY-MM-DD (default: today).",
    )
    parser.add_argument("--output", default="output/matches.xlsx", help="Output .xlsx path.")
    parser.add_argument(
        "--with-stats",
        action="store_true",
        help="Also visit each match page for Over/Under 2.5 odds and per-team 1.5/2.5/3.5 "
        "hit-rate stats (both via confirmed AJAX endpoints; slow — one extra page load per match).",
    )
    parser.add_argument(
        "--max-matches",
        type=int,
        default=None,
        help="Limit how many matches get per-match stats scraped (for testing).",
    )
    parser.add_argument("--no-headless", action="store_true", help="Show the browser window.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    date = dt.date.fromisoformat(args.date)
    driver = build_driver(headless=not args.no_headless)
    matches: list = []

    try:
        try:
            matches = scrape_day(driver, date)
            logging.info("Found %d matches for %s.", len(matches), date)
        except Exception:
            logging.exception(
                "Failed to scrape the match list for %s — nothing to save. "
                "See the exception above for what to check in selectors.py.",
                date,
            )
            raise

        if args.with_stats:
            targets = [m for m in matches if m.match_url][: args.max_matches]
            for i, match in enumerate(targets, start=1):
                logging.info(
                    "[%d/%d] Stats for %s vs %s", i, len(targets), match.home_team, match.away_team
                )
                try:
                    eligible, home_stats, away_stats, odds_ou = scrape_match_stats(
                        driver, match.match_url, match.home_team, match.away_team
                    )
                    match.stats_eligible = eligible
                    match.home_stats = home_stats
                    match.away_stats = away_stats
                    match.odds_ou = odds_ou
                except Exception:
                    logging.exception(
                        "Failed to get stats for %s vs %s — leaving stats blank for this "
                        "match and continuing with the rest.",
                        match.home_team,
                        match.away_team,
                    )
                time.sleep(1)  # be polite between match-page navigations
    finally:
        driver.quit()
        if matches:
            save_to_excel(matches, args.output)
            logging.info("Saved %s (%d matches).", args.output, len(matches))
        else:
            logging.warning("No matches collected — nothing saved to %s.", args.output)


if __name__ == "__main__":
    main()
