from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OddsWinner:
    """Rezultat final — tenisul nu are egalitate, deci doar 2 valori (spre
    deosebire de Odds1X2 la fotbal, care are home/draw/away)."""
    player1: Optional[float] = None
    player2: Optional[float] = None


@dataclass
class OddsTotalGames:
    """UNCONFIRMED market name/line set — Superbet arată "total game-uri"
    de la 18.5 la 26.5 pentru meciuri best-of-3; de confirmat exact ce linii
    sunt disponibile per turneu (best-of-3 vs. best-of-5 la Grand Slam)."""
    line: Optional[float] = None
    over: Optional[float] = None
    under: Optional[float] = None


@dataclass
class PlayerFormStats:
    """Statistici jucător de pe TennisExplorer — TOATE câmpurile de mai jos
    sunt placeholder, nimic confirmat încă despre structura reală a paginii
    de jucător. Completează/rescrie odată ce tools/inspect_page.py arată
    cum arată datele."""
    ranking: Optional[int] = None
    recent_form: Optional[str] = None  # ex. "W-W-L-W-L", ultimele 5 meciuri
    surface_win_pct: Optional[float] = None  # % victorii pe suprafața meciului curent
    matches_played_surface: Optional[int] = None
    injury_status: Optional[str] = None  # de obicei absent din date; NU exista un feed dedicat confirmat


@dataclass
class H2HStats:
    player1_wins: Optional[int] = None
    player2_wins: Optional[int] = None
    last_meeting: Optional[str] = None  # data/rezultat ultimului meci direct


@dataclass
class TennisMatch:
    tour: str  # "atp" | "wta" | "wta-125" | "challenger" | ... — vezi tournaments.py
    tournament: str
    surface: Optional[str] = None  # Zgură / Hard / Iarbă — apare pe pagina Superbet ("Suprafata de joc:")
    player1: str = ""
    player2: str = ""
    time_text: str = ""
    status: str = ""
    event_id: Optional[int] = None
    is_doubles: bool = False  # meciurile de dublu apar separat pe Superbet — de exclus sau marcat
    odds_winner: OddsWinner = field(default_factory=OddsWinner)
    odds_total_games: OddsTotalGames = field(default_factory=OddsTotalGames)
    player1_stats: PlayerFormStats = field(default_factory=PlayerFormStats)
    player2_stats: PlayerFormStats = field(default_factory=PlayerFormStats)
    h2h: H2HStats = field(default_factory=H2HStats)
    match_url: Optional[str] = None
    estimated_edge: Optional[str] = None  # notă de analiză, nu un calcul automat matematic garantat

    def to_flat_dict(self) -> dict:
        return {
            "tour": self.tour,
            "tournament": self.tournament,
            "surface": self.surface,
            "time": self.time_text,
            "status": self.status,
            "is_doubles": self.is_doubles,
            "player1": self.player1,
            "player2": self.player2,
            "odds_1": self.odds_winner.player1,
            "odds_2": self.odds_winner.player2,
            "games_line": self.odds_total_games.line,
            "games_over": self.odds_total_games.over,
            "games_under": self.odds_total_games.under,
            "p1_ranking": self.player1_stats.ranking,
            "p1_form": self.player1_stats.recent_form,
            "p1_surface_win_pct": self.player1_stats.surface_win_pct,
            "p2_ranking": self.player2_stats.ranking,
            "p2_form": self.player2_stats.recent_form,
            "p2_surface_win_pct": self.player2_stats.surface_win_pct,
            "h2h_p1_wins": self.h2h.player1_wins,
            "h2h_p2_wins": self.h2h.player2_wins,
            "h2h_last_meeting": self.h2h.last_meeting,
            "estimated_edge": self.estimated_edge,
            "match_url": self.match_url,
        }
