from __future__ import annotations

import argparse
import datetime as dt
import logging

from superbet_scraper.events import fetch_event_detail, fetch_events, parse_event, parse_over_under
from superbet_scraper.export import save_to_excel
from superbet_scraper.stats import (
    extract_table_id,
    extract_team_ids,
    fetch_fixture_overview,
    fetch_h2h,
    fetch_standings,
)
from superbet_scraper.tournaments import find_tournament, search_tournaments


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape odds + stats for a Superbet.ro football tournament/date.")
    parser.add_argument("--date", type=str, default=dt.date.today().isoformat(), help="YYYY-MM-DD (default: today)")
    parser.add_argument("--tournament", type=str, help='Tournament slug, e.g. "italia/serie-a" (country/league)')
    parser.add_argument("--search", type=str, help='List tournaments matching this text and exit (e.g. "italia")')
    parser.add_argument("--with-stats", action="store_true", help="Also fetch Over/Under odds, standings, and head-to-head history for each match.")
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

    if not args.tournament:
        parser.error("--tournament is required (or use --search to find the right slug first)")

    country_slug, _, league_slug = args.tournament.partition("/")
    tournament_id = find_tournament(country_slug, league_slug)
    if tournament_id is None:
        logging.error(
            "Tournament slug '%s' not found. Try: python main.py --search \"%s\"",
            args.tournament, country_slug,
        )
        return

    date = dt.date.fromisoformat(args.date)
    logging.info("Fetching events for tournament_id=%d (%s) on %s", tournament_id, args.tournament, date)

    raw_events = fetch_events([tournament_id], date)
    logging.info("Found %d matches.", len(raw_events))

    matches = []
    standings_cache: dict[str, list[dict]] = {}

    for i, raw_event in enumerate(raw_events, start=1):
        match = parse_event(raw_event)
        match.league = args.tournament
        match.event_id = raw_event.get("event_id")
        logging.info("[%d/%d] %s vs %s", i, len(raw_events), match.home_team, match.away_team)

        if args.with_stats and match.event_id:
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

                        # ASSUMPTION (unconfirmed beyond one manual check): fixture
                        # overview's team1 == the home team, team2 == away. Revisit
                        # if home/away ever look swapped in output.
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

        matches.append(match)

    save_to_excel(matches, args.output)
    logging.info("Saved %s (%d matches).", args.output, len(matches))


if __name__ == "__main__":
    main()
