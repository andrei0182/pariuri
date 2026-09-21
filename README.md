# pariuri

Monorepo consolidating three former repos -- `andrei0182/bet`, `andrei0182/SuperBet`,
and `andrei0182/tenis` -- each merged in with its full git history preserved
(via `git filter-repo` + `git merge --allow-unrelated-histories`, not squashed
or copy-pasted).

## Structure

```
football/
├── betexplorer/             # scraper package, from bet/betscraper/
├── superbet/                # scraper package, from SuperBet/superbet_scraper/
├── scrape_betexplorer.py    # from bet/main.py
├── scrape_superbet.py       # from SuperBet/main.py
├── daily_recommendations.py # cross-references both sources, sends the email
├── check_results.py         # backfills results for past pending picks
└── recommendations_log.csv  # persistent picks/results log (history preserved)

tennis/
├── tenis_scraper/
├── main.py
├── check_results.py
├── send_report_email.py
└── stats/picks_log.csv      # persistent picks/results log (history preserved)

.github/workflows/
├── daily-football.yml       # runs football/ pipeline, single checkout, no cross-repo checkout
└── daily-tennis.yml         # runs tennis/ pipeline

requirements.txt              # single unified dependency list for both pipelines
```

## Football pipeline

Previously required checking out `andrei0182/bet` alongside `andrei0182/SuperBet`
in CI. Now everything lives in `football/` in this repo, so the workflow does a
single checkout and runs both scrapers with `--output` pointed at separate
subdirectories (`football/betexplorer_output/`, `football/superbet_output/`) to
avoid collisions, then feeds both into `daily_recommendations.py`.

## Tennis pipeline

Content and structure under `tennis/` are unchanged from the original
`andrei0182/tenis` repo; only its location (now nested under `tennis/`) and the
workflow that drives it (`.github/workflows/daily-tennis.yml`, updated paths)
changed.

## Setup

```bash
pip install -r requirements.txt
```

Both workflows are also triggerable manually via `workflow_dispatch` from the
Actions tab, useful for testing outside the 03-09 Romania-time morning window.
