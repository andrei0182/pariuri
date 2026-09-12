"""
Every CSS selector the scraper uses, in one place.

IMPORTANT — READ THIS FIRST:
This sandbox's outbound network policy blocks betexplorer.com, so these values
could not be confirmed against the live DOM. They are best-effort defaults
based on the general BetExplorer page layout (a "table-main" style match
table, tabbed odds views, a per-match "Standings" tab). Before relying on
this scraper, run `tools/inspect_page.py <url>` from a machine that CAN reach
the site (this is Step 2 of the task, automated): it dumps every table,
tab/dropdown, and "standings"-like element it finds with its selector, so you
can paste the corrected values in here in one place.

Nothing outside this file should hard-code a selector.
"""

# ---- Date navigation (Step 3) ------------------------------------------------
# BetExplorer paginates results by day via a URL query string on the results
# page. Confirm the exact param names in DevTools > Network while clicking the
# calendar, then adjust this template. {year}/{month:02d}/{day:02d} are filled
# in by betscraper.match_list.build_date_url().
BASE_URL = "https://www.betexplorer.com"
SPORT_PATH = "/football/"
DATE_URL_TEMPLATE = BASE_URL + SPORT_PATH + "?year={year}&month={month:02d}&day={day:02d}"

# ---- Match list page (Step 4) ------------------------------------------------
MATCH_TABLE = "table.table-main"
MATCH_ROW = "table.table-main tbody tr"
LEAGUE_HEADER_ROW = "tr.table-main__head"  # section header rows that separate leagues
TEAM_HOME_CELL = "td.table-main__tt span.table-main__tt-home, td.h-text-left a"
TEAM_AWAY_CELL = "td.table-main__tt span.table-main__tt-away"
TIME_OR_STATUS_CELL = "td.table-main__time, td.h-text-center.h-text-no-wrap"
SCORE_CELL = "td.table-main__score"
ODDS_CELLS = "td.table-main__odds"
MATCH_LINK = "a"  # relative <a href> inside the row that points at the match detail page

# ---- Live / completed / scheduled detection (Step 6) -------------------------
LIVE_ROW_CLASS = "in-play"          # row or time-cell class BetExplorer uses for live matches
LIVE_TIMER_CELL = "span.min-scr"    # the running-clock element shown instead of a fixed time
COMPLETED_SCORE_PATTERN = r"^\d+:\d+$"

# ---- Odds view switch: 1X2 -> Over/Under 2.5 (Step 5) -------------------------
ODDS_VIEW_DROPDOWN = "select.js-select-odds, div.odds-type-selector"
ODDS_VIEW_OPTION_OU25 = "option[value*='over-under'], a[data-odds='ou-2.5']"

# ---- Match detail page (Steps 7-8) -------------------------------------------
STANDINGS_TABLE = "div#standings, table.table-standings"  # presence check == stats-eligible
OU_TAB_ROOT = "div#tab-over-under, div.tabs-inner"
OU_SUBTAB_1_5 = "a[data-odd='1.5'], li[data-value='1.5'] a"
OU_SUBTAB_2_5 = "a[data-odd='2.5'], li[data-value='2.5'] a"
OU_SUBTAB_3_5 = "a[data-odd='3.5'], li[data-value='3.5'] a"
OU_HOME_STATS_CELL = "table.table-over-under tbody tr:nth-child(1) td"
OU_AWAY_STATS_CELL = "table.table-over-under tbody tr:nth-child(2) td"
