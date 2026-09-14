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
class Match:
    league: str
    home_team: str
    away_team: str
    time_text: str
    status: str  # "NOT_STARTED" | other values seen in inplay_stats_metadata.status — confirm full set
    event_id: Optional[int] = None
    odds_1x2: Odds1X2 = field(default_factory=Odds1X2)
    odds_ou: OddsOverUnder = field(default_factory=OddsOverUnder)
    stats_available: bool = False
    home_rank: Optional[int] = None
    home_points: Optional[str] = None
    home_form: Optional[str] = None
    away_rank: Optional[int] = None
    away_points: Optional[str] = None
    away_form: Optional[str] = None
    h2h_home_wins: Optional[int] = None
    h2h_draws: Optional[int] = None
    h2h_away_wins: Optional[int] = None
    h2h_since: Optional[int] = None
    match_url: Optional[str] = None

    def to_flat_dict(self) -> dict:
        return {
            "league": self.league,
            "time": self.time_text,
            "status": self.status,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "odds_1": self.odds_1x2.home,
            "odds_x": self.odds_1x2.draw,
            "odds_2": self.odds_1x2.away,
            "ou_line": self.odds_ou.line,
            "odds_over": self.odds_ou.over,
            "odds_under": self.odds_ou.under,
            "stats_available": self.stats_available,
            "home_rank": self.home_rank,
            "home_points": self.home_points,
            "home_form": self.home_form,
            "away_rank": self.away_rank,
            "away_points": self.away_points,
            "away_form": self.away_form,
            "h2h_home_wins": self.h2h_home_wins,
            "h2h_draws": self.h2h_draws,
            "h2h_away_wins": self.h2h_away_wins,
            "h2h_since": self.h2h_since,
            "match_url": self.match_url,
        }
