from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Odds1X2:
    home: Optional[float] = None
    draw: Optional[float] = None
    away: Optional[float] = None


@dataclass
class OddsOverUnder:
    line: float = 2.5
    over: Optional[float] = None
    under: Optional[float] = None


@dataclass
class TeamOverUnderStats:
    """Over/Under hit-rate values as shown on BetExplorer's per-match 'Overall' tab."""

    over_1_5: Optional[str] = None
    under_1_5: Optional[str] = None
    over_2_5: Optional[str] = None
    under_2_5: Optional[str] = None
    over_3_5: Optional[str] = None
    under_3_5: Optional[str] = None


@dataclass
class Match:
    league: str
    home_team: str
    away_team: str
    time_text: str
    status: str  # "scheduled" | "live" | "completed"
    score: Optional[str] = None
    partial_score: Optional[str] = None  # confirmed live: e.g. "(0:0, 0:1)" — half/period breakdown, from td.table-main__partial
    match_url: Optional[str] = None
    odds_1x2: Odds1X2 = field(default_factory=Odds1X2)
    odds_ou: OddsOverUnder = field(default_factory=OddsOverUnder)
    stats_eligible: Optional[bool] = None
    home_stats: Optional[TeamOverUnderStats] = None
    away_stats: Optional[TeamOverUnderStats] = None

    def match_key(self) -> str:
        """Key used to merge the 1X2 table row with the Over/Under table row for the same fixture.

        Prefers match_url: it's a stable per-fixture identifier that doesn't
        change between the two page states. Falls back to
        (home, away, time_text) only when a row has no link, but that combo is
        fragile — if a match goes live between the 1X2 load and the O/U-view
        switch, its time cell can change from a fixed kickoff time to a
        running clock, silently breaking the merge for that row.
        """
        if self.match_url:
            return self.match_url
        return f"{self.home_team.strip().lower()}|{self.away_team.strip().lower()}|{self.time_text.strip()}"

    def to_flat_dict(self) -> dict:
        stats = self.home_stats or TeamOverUnderStats()
        astats = self.away_stats or TeamOverUnderStats()
        return {
            "league": self.league,
            "time": self.time_text,
            "status": self.status,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "score": self.score,
            "partial_score": self.partial_score,
            "odds_1": self.odds_1x2.home,
            "odds_x": self.odds_1x2.draw,
            "odds_2": self.odds_1x2.away,
            "ou_line": self.odds_ou.line,
            "odds_over": self.odds_ou.over,
            "odds_under": self.odds_ou.under,
            "stats_eligible": self.stats_eligible,
            "home_over_1.5": stats.over_1_5,
            "home_under_1.5": stats.under_1_5,
            "home_over_2.5": stats.over_2_5,
            "home_under_2.5": stats.under_2_5,
            "home_over_3.5": stats.over_3_5,
            "home_under_3.5": stats.under_3_5,
            "away_over_1.5": astats.over_1_5,
            "away_under_1.5": astats.under_1_5,
            "away_over_2.5": astats.over_2_5,
            "away_under_2.5": astats.under_2_5,
            "away_over_3.5": astats.over_3_5,
            "away_under_3.5": astats.under_3_5,
            "match_url": self.match_url,
        }
