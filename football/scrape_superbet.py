from __future__ import annotations

import argparse
import datetime as dt
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from superbet.events import fetch_event_detail, fetch_events, fetch_events_for_all_tournaments, parse_event, parse_over_under
from superbet.export import save_to_excel
from superbet.stats import (
    extract_table_id,
    extract_team_ids,
    fetch_fixture_overview,
    fetch_h2h,
    fetch_standings,
)
from superbet.tournaments import all_football_tournament_ids, find_tournament, reverse_lookup, search_tournaments


def enrich_match(match, standings_cache: dict) -> None:
    """Fetch Over/Under odds, standings, and h2h for one match, mutating it
    in place. standings_cache is shared across threads — a race where two
    threads both miss the cache for a brand-new table_id just means it gets
    fetched twice, which is harmless (no lock needed for this)."""
    if not match.event_id:
        return
    try:
        detail = fetch_event_detail(match.event_id)
        if detail:
            match.odds_ou = parse_over_under(detail, line=2.5)

        overview = fetch_fixture_overview(match.event_id)
        if overview:
            table_id = extract_table_id(overview)
            team1_id, team2_id = extract_team_ids(overview)

            if table_id:
                if table_id not in standings_cache:
                    standings_cache[table_id] = fetch_standings(table_id)
                standings = standings_cache[table_id]
                by_id = {row["team_id"]: row for row in standings}

                home_row = by_id.get(team1_id)
                away_row = by_id.get(team2_id)
                if home_row:
                    match.home_rank = home_row.get("rank")
                    match.home_points = home_row.get("points")
                    match.home_form = home_row.get("form")
                if away_row:
                    match.away_rank = away_row.get("rank")
                    match.away_points = away_row.get("points")
                    match.away_form = away_row.get("form")
                match.stats_available = bool(home_row or away_row)

            if team1_id and team2_id:
                h2h = fetch_h2h(team1_id, team2_id)
                if h2h:
                    stats = h2h.get("h2h_statistics", {})
                    match.h2h_home_wins = stats.get("team1")
                    match.h2h_draws = stats.get("draw")
                    match.h2h_away_wins = stats.get("team2")
                    match.h2h_since = h2h.get("h2h_year_since")
    except Exception:
        logging.exception("Failed to fetch stats for %s vs %s — leaving stats blank.", match.home_team, match.away_team)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape odds + stats for Superbet.ro football matches.")
    parser.add_argument("--date", type=str, default=dt.date.today().isoformat(), help="YYYY-MM-DD (default: today)")
    parser.add_argument("--tournament", type=str, help='Single tournament slug, e.g. "italia/serie-a" (country/league)')
    parser.add_argument("--all", action="store_true", help="Fetch every football match for the date, across ALL tournaments.")
    parser.add_argument("--search", type=str, help='List tournaments matching this text and exit (e.g. "italia")')
    parser.add_argument("--with-stats", action="store_true", help="Also fetch Over/Under odds, standings, and head-to-head history for each match.")
    parser.add_argument("--workers", type=int, default=8, help="Concurrent threads for fetching (default: 8).")
    parser.add_argument("--output", type=str, default="output/matches.xlsx", help="Output Excel path")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

    if args.search:
        results = search_tournaments(args.search)
        print(f"Found {len(results)} tournaments matching '{args.search}':")
        for slug, tid in sorted(results.items()):
            print(f"  {slug} -> {tid}")
        return

    if not args.tournament and not args.all:
        parser.error("Specify --tournament SLUG, or --all for every league (or --search to find a slug first)")

    date = dt.date.fromisoformat(args.date)
    matches = []

    if args.all:
        tournament_ids = all_football_tournament_ids()
        logging.info("Fetching events for %d tournaments on %s (this may take a minute)...", len(tournament_ids), date)
        raw_events = fetch_events_for_all_tournaments(tournament_ids, date, workers=args.workers)
        logging.info("Found %d matches across all leagues.", len(raw_events))

        for raw_event in raw_events:
            match = parse_event(raw_event)
            tid = raw_event.get("fixture", {}).get("tournament_id")
            match.league = reverse_lookup(tid) or str(tid)
            match.event_id = raw_event.get("event_id")
            matches.append(match)
    else:
        country_slug, _, league_slug = args.tournament.partition("/")
        tournament_id = find_tournament(country_slug, league_slug)
        if tournament_id is None:
            logging.error("Tournament slug '%s' not found. Try: python main.py --search \"%s\"", args.tournament, country_slug)
            return

        logging.info("Fetching events for tournament_id=%d (%s) on %s", tournament_id, args.tournament, date)
        raw_events = fetch_events([tournament_id], date)
        logging.info("Found %d matches.", len(raw_events))

        for raw_event in raw_events:
            match = parse_event(raw_event)
            match.league = args.tournament
            match.event_id = raw_event.get("event_id")
            matches.append(match)

    if args.with_stats:
        standings_cache: dict = {}
        done = 0
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(enrich_match, m, standings_cache): m for m in matches}
            for future in as_completed(futures):
                done += 1
                m = futures[future]
                future.result()  # surface any exception enrich_match didn't already log
                logging.info("[%d/%d] %s vs %s", done, len(matches), m.home_team, m.away_team)

    save_to_excel(matches, args.output)
    logging.info("Saved %s (%d matches).", args.output, len(matches))

    # Quick terminal summary for Over 2.5
    over_odds = [m.odds_ou.over for m in matches if m.odds_ou.over]
    if over_odds:
        avg_over = sum(over_odds) / len(over_odds)
        print()
        print(f"Over 2.5 summary: {len(over_odds)}/{len(matches)} matches have an Over 2.5 price, avg odds = {avg_over:.2f}")


if __name__ == "__main__":
    main()
