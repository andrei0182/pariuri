from __future__ import annotations

import argparse
import datetime as dt
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

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
        help="Also fetch Over/Under 2.5 odds and per-team 1.5/2.5/3.5 hit-rate stats for each "
        "match, via plain HTTP requests (fast — no extra browser page load per match).",
    )
    parser.add_argument(
        "--max-matches",
        type=int,
        default=None,
        help="Limit how many matches get per-match stats scraped (for testing).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help="Concurrent threads for --with-stats' per-match HTTP requests (default: 3 — "
        "higher values risk 429 Too Many Requests from the site under sustained load).",
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

            def _fetch_one(match):
                return match, scrape_match_stats(match.match_url, match.home_team, match.away_team)

            done = 0
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = [pool.submit(_fetch_one, match) for match in targets]
                for future in as_completed(futures):
                    done += 1
                    try:
                        match, (eligible, home_stats, away_stats, odds_ou, odds_1x2) = future.result()
                    except Exception:
                        logging.exception(
                            "[%d/%d] Failed to get stats for a match — leaving stats blank "
                            "for it and continuing with the rest.",
                            done, len(targets),
                        )
                        continue
                    match.stats_eligible = eligible
                    match.home_stats = home_stats
                    match.away_stats = away_stats
                    match.odds_ou = odds_ou
                    match.odds_1x2 = odds_1x2  # AJAX-fetched, more reliable than the list-page DOM scrape
                    logging.info(
                        "[%d/%d] Stats for %s vs %s", done, len(targets), match.home_team, match.away_team
                    )
    finally:
        driver.quit()
        if matches:
            save_to_excel(matches, args.output)
            logging.info("Saved %s (%d matches).", args.output, len(matches))
        else:
            logging.warning("No matches collected — nothing saved to %s.", args.output)


if __name__ == "__main__":
    main()
