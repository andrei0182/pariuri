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
# CONFIRMED (2026-09-12, via a live fetch of a real date link on the site):
# https://www.betexplorer.com/football/results/?year=2026&month=09&day=10
# The query-string format guessed originally (?year=&month=&day=) was
# actually correct — the bug was the PATH: it's /football/results/, not
# /football/. This page shows completed results for that date (scores,
# period-by-period breakdown, POSTP./AET/AfP markers) across all leagues —
# same table.table-main structure confirmed for the odds-filter page, with
# extra score-related cells not yet selector-confirmed (see SCORE_CELL note
# below). Not yet confirmed: whether this same path+param pattern also
# surfaces upcoming/scheduled matches for a future date, or only completed
# ones — test with today's date and a future date before assuming both work.
BASE_URL = "https://www.betexplorer.com"
SPORT_PATH = "/football/results/"
DATE_URL_TEMPLATE = BASE_URL + SPORT_PATH + "?year={year}&month={month:02d}&day={day:02d}"

# ---- Match list page (Step 4) ------------------------------------------------
# CONFIRMED against the live page's actual outerHTML (2026-09-12, via
# tools/inspect_page.py on https://www.betexplorer.com/football/odds-filter/):
#   <tr><th class="h-text-left">LEAGUE NAME</th><th class="table-main__odds">1</th>...</tr>  (header row)
#   <tr>
#     <td class="table-main__tt">
#       <span class="table-main__time">17:00</span>
#       <a href="/football/.../match-slug/ID/">Home Team - Away Team</a>
#     </td>
#     <td class="table-main__streams"></td>
#     <td class="table-main__odds">5.27</td>
#     <td class="table-main__odds">3.50</td>
#     <td class="table-main__odds fav-odd">1.56</td>
#   </tr>
MATCH_TABLE = "table.table-main"          # confirmed: matches table.table-main.js-tablebanner-t (class selector matches on any element with that class among others)
MATCH_ROW = "table.table-main tr"
LEAGUE_HEADER_ROW = "th"  # presence of a <th> child inside the row == it's a league header, not a match — the class on header rows is inconsistent across pages (empty on /odds-filter/, "js-tournament" on /results/), so detect structurally instead of by class
LEAGUE_HEADER_NAME_CELL = "th.h-text-left"  # league name + link to the league page
TIME_CELL = "td.table-main__tt span.table-main__time"  # confirmed: "17:00" — separate element, NOT concatenated with the team names
TEAM_LINK_CELL = "td.table-main__tt a"  # confirmed: text is "Home Team - Away Team"; href is the match detail page
SCORE_CELL = "td.table-main__result"  # confirmed: text "0:1" (or "POSTP." for postponed matches — doesn't match COMPLETED_SCORE_PATTERN below, a known gap), href to the match page
# NOT YET CONFIRMED: a live match's row has NEITHER SCORE_CELL nor an empty
# ODDS_CELLS — it keeps 3 populated td.table-main__odds (odds tick live) AND
# gets a td.table-main__streams[data-live-cell="score"] cell instead of
# table-main__result, which was empty (0 goals so far) in the one live
# match caught during development. Match.score will stay None for live
# matches until this cell's populated format is confirmed against a match
# that has actually scored — check LIVE_SCORE_CELL below once you have one.
LIVE_SCORE_CELL = "td.table-main__streams[data-live-cell='score']"  # placeholder selector, content format unconfirmed
PARTIAL_SCORE_CELL = "td.table-main__partial"  # confirmed: text "(0:0, 0:1)" — per-half/period breakdown, bonus data not in the original spec but cheap to capture
# CONFIRMED: a single day's results page (/football/results/?year=&month=&day=)
# mixes BOTH row kinds for that date: completed matches (SCORE_CELL +
# PARTIAL_SCORE_CELL present, no ODDS_CELLS) and later-that-day scheduled
# matches (ODDS_CELLS present, no SCORE_CELL) — see match_list.py's
# _extract_match_row, which branches on which is present rather than
# assuming one or the other for the whole page.
ODDS_CELLS = "td.table-main__odds"  # confirmed: plain text inside (e.g. "5.27") once the page has fully loaded — NOT a data-odd attribute (an earlier run caught these empty before the odds had finished rendering; give the page time to settle, which _wait_for_stable_dom-style waiting handles)
FAVORITE_ODD_CELL = "td.table-main__odds.fav-odd"  # marks whichever of the 3 is currently lowest — cosmetic only, order of the 3 is always [home, draw, away]
MATCH_LINK = "td.table-main__tt a"  # confirmed — same element as TEAM_LINK_CELL

# ---- Live / completed / scheduled detection (Step 6) -------------------------
# ---- Live / completed / scheduled detection (Step 6) -------------------------
# CONFIRMED (2026-09-12, via a live in-progress match on the results page):
# there is NO css class involved for live rows at all — the original
# LIVE_ROW_CLASS/LIVE_TIMER_CELL guesses were wrong. A live match's <tr>
# instead carries a data-live="<match_id>" attribute directly, e.g.:
#   <tr data-live="YZlX9Wv1" data-dt="12,9,2026,18,00" data-dt-now="12,9,2026,18,19">
# Bonus, not yet used by the scraper but confirmed present on every row:
# data-dt="D,M,Y,H,Min" is the kickoff datetime, and data-dt-now is the
# server's clock at render time — both more reliable than the visible time
# span's text, which can show a DIFFERENT hour than data-dt (a timezone
# display quirk was caught live: span text "19:00" vs data-dt hour "20").
# If kickoff-time accuracy matters, prefer parsing data-dt over TIME_CELL's
# text.
LIVE_ROW_ATTR = "data-live"
COMPLETED_SCORE_PATTERN = r"^\d+:\d+"

# ---- Odds view switch: 1X2 -> Over/Under 2.5 (Step 5) -------------------------

# ---- Over/Under odds via AJAX endpoint (confirmed, replaces the whole
# switch_to_over_under/OU_TAB_ROOT/OU_SUBTAB_* premise above) ------------------
# CONFIRMED (2026-09-12, via DevTools Network tab on a real match): O/U odds
# come from a same-origin JSON endpoint, called by the site's own JS when you
# click the "O/U" tab — not from any list page and not from clicking through
# tabs on the match page in a Selenium-visible way:
#   {BASE_URL}/match-odds/{match_id}/0/ou/bestOdds/?lang=en
# Response is {"odds": "<html...>"} — an HTML fragment, NOT the whole page.
# It does NOT need the `ts` session token that other endpoints on this site
# require, but DOES need cookies (age-gate/consent) already set, so it must
# still be called from within a Selenium session that has loaded the site
# at least once — a bare `requests.get()` won't work.
# Inside that HTML fragment, each total line (0.5, 1.5, 2.5, 3.5, ...) has:
#   <div data-all-handicap="2.50" class="... oddsComparisonAll__bestOdds"
#        data-hp-1="2.11" data-hp-2="1.74">
# data-hp-1 is the aggregate best/average Over odd, data-hp-2 the Under odd,
# for that handicap line — already computed by the site, no need to parse
# individual bookmaker rows. See betscraper/match_odds.py.
OU_AJAX_URL_TEMPLATE = BASE_URL + "/match-odds/{match_id}/0/ou/bestOdds/?lang=en"

# ---- Per-team Over/Under hit-rate stats (Steps 7-8) — still NOT CONFIRMED ----
# The OU_AJAX endpoint above gives betting ODDS for this match (what a
# bookmaker pays out), not each team's historical Over/Under hit-rate
# (e.g. "Arsenal have gone Over 2.5 in 8 of their last 10") — that's a
# different, still-unconfirmed data source. A likely candidate spotted but
# not yet inspected: {league_url}standings/?table=over_under&table_sub=overall&event_context={match_id}
# (found alongside the OU_AJAX call in the same Network capture). Confirm its
# response format before using it — it may need the `ts` token the OU_AJAX
# endpoint didn't.
STANDINGS_OU_TAB_XPATH = "//a[contains(@class, 'standings__submenu-a') and normalize-space(.)='Over/Under']"  # CONFIRMED 2026-09-13 — clicking this tab injects the O/U hit-rate tables (table-type-6-*) into the DOM; its absence means this match has no standings widget (cup/friendly/single-leg tie)

# ---- Overlay dismissal: age gate + cookie consent -----------------------------
# BetExplorer shows an 18+ age-verification interstitial on first load, and
# likely a cookie-consent banner on top of that — both block the match table
# from ever becoming visible/interactable, regardless of whether MATCH_ROW
# below is correct. These were NOT verified against the live site either (same
# network restriction as everything else here), so they are generic,
# broadly-compatible patterns for common consent-management frameworks
# (OneTrust, Cookiebot, Quantcast) plus a text-based fallback for a custom
# "confirm you are 18+" button. betscraper.consent.dismiss_overlays() tries
# each in turn and silently continues if none match — update/add selectors
# here once you've seen the real markup (tools/inspect_page.py --keep-open
# will show it, or just open DevTools on first load).
AGE_GATE_CONFIRM_BUTTONS = [
    "button#age-gate-confirm",
    "a#age-gate-confirm",
    ".age-verification button.confirm",
    "[data-testid='age-gate-confirm']",
]
# XPath fallback: any clickable element whose visible text matches an
# affirmative age-confirmation phrase (case-insensitive, several languages
# since betexplorer.com serves localized copy).
AGE_GATE_CONFIRM_XPATH = (
    "//button[contains(translate(text(),"
    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'18')] | "
    "//a[contains(translate(text(),"
    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'18')]"
)

COOKIE_CONSENT_BUTTONS = [
    "#onetrust-accept-btn-handler",       # OneTrust
    ".CybotCookiebotDialogBodyButton",    # Cookiebot
    "#qc-cmp2-ui button[mode='primary']",  # Quantcast
    "button#cookie-accept",
    ".cookie-consent button.accept",
]
