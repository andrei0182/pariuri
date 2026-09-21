from __future__ import annotations

import os

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from .models import Match

# Internal (English) column keys stay unchanged so any script reading the
# in-memory DataFrame from matches_to_dataframe() keeps working as before.
# Only the EXPORTED Excel file's header text is translated/described here —
# note this means a pd.read_excel() on the saved .xlsx now sees these
# Romanian labels as its column names, not the English keys below.
_COLUMN_LABELS = {
    "date": "Match Date",
    "league": "League",
    "time": "Kick-off Time",
    "status": "Status",
    "home_team": "Home Team",
    "away_team": "Away Team",
    "score": "Final Score",
    "partial_score": "Half-time Score",
    "odds_1": "Odds 1",
    "odds_x": "Odds X",
    "odds_2": "Odds 2",
    "ou_line": "O/U Line",
    "odds_over": "Odds Over",
    "odds_under": "Odds Under",
    "stats_eligible": "Stats Available",
    "home_over_1.5": "Home Over 1.5 (matches)",
    "home_under_1.5": "Home Under 1.5 (matches)",
    "home_over_2.5": "Home Over 2.5 (matches)",
    "home_under_2.5": "Home Under 2.5 (matches)",
    "home_over_3.5": "Home Over 3.5 (matches)",
    "home_under_3.5": "Home Under 3.5 (matches)",
    "away_over_1.5": "Away Over 1.5 (matches)",
    "away_under_1.5": "Away Under 1.5 (matches)",
    "away_over_2.5": "Away Over 2.5 (matches)",
    "away_under_2.5": "Away Under 2.5 (matches)",
    "away_over_3.5": "Away Over 3.5 (matches)",
    "away_under_3.5": "Away Under 3.5 (matches)",
    "prob_over_1.5": "Probability Over 1.5",
    "prob_over_2.5": "Probability Over 2.5",
    "prob_over_3.5": "Probability Over 3.5",
    "match_url": "Match Link",
    # Summary-sheet keys
    "match_count": "Matches",
    "stats_pct": "Stats Coverage (%)",
    "avg_odds_over": "Avg Odds Over 2.5",
    "avg_odds_under": "Avg Odds Under 2.5",
    "avg_prob_over_2_5": "Avg Probability Over 2.5",
}

_MAIN_PERCENT_COLUMNS = {"prob_over_1.5", "prob_over_2.5", "prob_over_3.5"}
_MAIN_ODDS_COLUMNS = {"odds_1", "odds_x", "odds_2", "odds_over", "odds_under"}
_SUMMARY_PERCENT_COLUMNS = {"stats_pct", "avg_prob_over_2_5"}
_SUMMARY_ODDS_COLUMNS = {"avg_odds_over", "avg_odds_under"}


def matches_to_dataframe(matches: list[Match]) -> pd.DataFrame:
    return pd.DataFrame(m.to_flat_dict() for m in matches)


def _hit_rate(over_val, under_val) -> float | None:
    """One side's blended hit-rate for a line, as a 0-1 fraction, or None if
    either count is missing/non-numeric (e.g. no standings data for that
    team's league — see stats_eligible)."""
    try:
        over = int(over_val)
        under = int(under_val)
    except (TypeError, ValueError):
        return None
    total = over + under
    if total == 0:
        return None
    return over / total


def add_probability_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Adds prob_over_{line} columns (0-1 fraction) for each O/U line with
    hit-rate stats, computed as the average of the home and away teams' own
    season-long hit rates for that line — e.g. if the home team has gone
    Over 2.5 in 18 of 25 games (72%) and the away team in 19 of 25 (76%),
    prob_over_2.5 for this match is 74%.

    This is a straightforward blended estimate from each team's own record,
    not a bookmaker-derived or Poisson-model probability — a transparent
    starting point a person can sanity-check against the underlying counts
    (which stay in the sheet alongside it). Blank when neither team has
    hit-rate data for that line (e.g. cup matches with no standings table).
    """
    df = df.copy()
    for line_key in ("1.5", "2.5", "3.5"):
        home_over_col, home_under_col = f"home_over_{line_key}", f"home_under_{line_key}"
        away_over_col, away_under_col = f"away_over_{line_key}", f"away_under_{line_key}"

        def _row_prob(row, ho=home_over_col, hu=home_under_col, ao=away_over_col, au=away_under_col):
            rates = [
                r for r in (_hit_rate(row.get(ho), row.get(hu)), _hit_rate(row.get(ao), row.get(au)))
                if r is not None
            ]
            return sum(rates) / len(rates) if rates else None

        df[f"prob_over_{line_key}"] = df.apply(_row_prob, axis=1)
    return df


def build_league_summary(df: pd.DataFrame) -> pd.DataFrame:
    """One row per league (plus an overall TOTAL row first): match counts,
    stats coverage, and averaged odds/probability — a quick statistical
    overview to scan before drilling into individual matches."""

    def _summarize(group: pd.DataFrame, league_label: str) -> dict:
        total = len(group)
        eligible = int(group["stats_eligible"].fillna(False).astype(bool).sum())
        return {
            "league": league_label,
            "match_count": total,
            "stats_pct": (eligible / total) if total else None,
            "avg_odds_over": group["odds_over"].mean() if group["odds_over"].notna().any() else None,
            "avg_odds_under": group["odds_under"].mean() if group["odds_under"].notna().any() else None,
            "avg_prob_over_2_5": group["prob_over_2.5"].mean() if group["prob_over_2.5"].notna().any() else None,
        }

    if df.empty:
        return pd.DataFrame(columns=["league", "match_count", "stats_pct", "avg_odds_over", "avg_odds_under", "avg_prob_over_2_5"])

    rows = [_summarize(df, "TOTAL")]
    for league, group in df.groupby("league", sort=True):
        rows.append(_summarize(group, league))
    return pd.DataFrame(rows)


def build_high_confidence_over25(df: pd.DataFrame) -> pd.DataFrame:
    """Matches where Probability Over 2.5 is exactly 100% — both teams have
    gone Over 2.5 in every game of theirs this season (see
    add_probability_columns). Only the columns needed to place a bet on
    one: league, kick-off time, both teams, and the Over 2.5 odds.
    """
    cols = [
        "league", "time", "home_team", "away_team", "odds_over", "prob_over_2.5",
        "home_over_2.5", "home_under_2.5", "away_over_2.5", "away_under_2.5",
        "match_url",
    ]
    if df.empty or "prob_over_2.5" not in df.columns:
        return pd.DataFrame(columns=cols)
    filtered = df[df["prob_over_2.5"] >= 0.90][cols].copy()
    return filtered.sort_values(["league", "time"]).reset_index(drop=True)


def _style_sheet(ws, df: pd.DataFrame, percent_cols: set[str], odds_cols: set[str]) -> None:
    """Bold/colored header with the descriptive label text, frozen header
    row, auto-sized columns, percentage/odds number formats, and a proper
    Excel Table over the data range (gives native sort/filter dropdowns in
    Excel — this is what makes the sheet 'easy to sort')."""
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")

    for col_idx, col_key in enumerate(df.columns, start=1):
        label = _COLUMN_LABELS.get(col_key, col_key)
        cell = ws.cell(row=1, column=col_idx, value=label)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        letter = get_column_letter(col_idx)
        # NOTE: pandas' .astype(str) can leave NaN/None as a raw float
        # instead of converting it to the string "nan" — convert explicitly
        # per value instead of relying on it.
        sample_values = [str(v) if pd.notna(v) else "" for v in df[col_key].head(200).tolist()]
        max_len = max([len(label)] + [len(v) for v in sample_values])
        ws.column_dimensions[letter].width = min(max(max_len + 2, 10), 42)

        if col_key in percent_cols:
            for row_idx in range(2, len(df) + 2):
                ws.cell(row=row_idx, column=col_idx).number_format = "0.0%"
        elif col_key in odds_cols:
            for row_idx in range(2, len(df) + 2):
                ws.cell(row=row_idx, column=col_idx).number_format = "0.00"

    ws.freeze_panes = "A2"

    if len(df) > 0:
        last_col_letter = get_column_letter(len(df.columns))
        table_ref = f"A1:{last_col_letter}{len(df) + 1}"
        safe_name = "".join(c for c in ws.title if c.isalnum()) or "Data"
        table = Table(displayName=f"{safe_name}Table", ref=table_ref)
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2", showFirstColumn=False, showLastColumn=False,
            showRowStripes=True, showColumnStripes=False,
        )
        ws.add_table(table)


def save_to_excel(matches: list[Match], path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    df = matches_to_dataframe(matches)
    df = add_probability_columns(df)
    summary_df = build_league_summary(df)
    high_confidence_df = build_high_confidence_over25(df)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        # Write data only (no pandas header) — we write our own styled,
        # descriptive header row directly below via _style_sheet.
        df.to_excel(writer, sheet_name="Matches", index=False, header=False, startrow=1)
        summary_df.to_excel(writer, sheet_name="League Summary", index=False, header=False, startrow=1)
        high_confidence_df.to_excel(writer, sheet_name="100% Over 2.5", index=False, header=False, startrow=1)

        _style_sheet(writer.sheets["Matches"], df, _MAIN_PERCENT_COLUMNS, _MAIN_ODDS_COLUMNS)
        _style_sheet(writer.sheets["League Summary"], summary_df, _SUMMARY_PERCENT_COLUMNS, _SUMMARY_ODDS_COLUMNS)
        _style_sheet(writer.sheets["100% Over 2.5"], high_confidence_df, {"prob_over_2.5"}, {"odds_over"})
