from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

BASE_URL = "https://www.tennisexplorer.com"
MATCH_DETAIL_URL = BASE_URL + "/match-detail/?id={match_id}"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_session = requests.Session()
_session.headers.update({"User-Agent": _USER_AGENT})
_retry = Retry(total=5, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504], respect_retry_after_header=True)
_session.mount("https://", HTTPAdapter(max_retries=_retry))
_session.mount("http://", HTTPAdapter(max_retries=_retry))

# CONFIRMAT (2026-09-15) prin inspectie reala pe
# /match-detail/?id=3323237 (Parry vs Stearns, Guadalajara WTA):
# o singura pagina match-detail contine tot ce ne trebuie pentru ambii
# jucatori simultan - nu mai e nevoie sa vizitam pagina fiecarui jucator
# separat pentru asta.
#
# Structura confirmata:
# - table.gDetail: profil comparat (rank, data nasterii, inaltime,
#   greutate, mana, "turned pro") - header cu numele jucatorilor, apoi
#   randuri [valoare_p1, eticheta, valoare_p2]
# - primul table.balance (fara randuri de an): record pe suprafata
#   comparat direct, coloane [Suprafata, P1, P2]
# - doua table.mutual: istoric recent de meciuri, unul per jucator (NU
#   H2H reciproc - sunt meciurile fiecaruia impotriva oricui, cele mai
#   recente primele)
# - H2H reciproc real: div.head cu textul "Head-to-head", urmat fie de
#   div.no-data ("No head-to-head record.") daca nu s-au intalnit
#   niciodata, fie (NEconfirmat structura exacta - perechea testata nu
#   avea H2H) de un tabel cu istoricul intalnirilor directe


@dataclass
class PlayerProfile:
    name: str = ""
    ranking: Optional[str] = None
    birthdate: Optional[str] = None
    height: Optional[str] = None
    weight: Optional[str] = None
    plays: Optional[str] = None
    turned_pro: Optional[str] = None


@dataclass
class RecentMatch:
    tournament: str = ""
    round: str = ""
    date: str = ""
    opponent: str = ""
    score: str = ""
    won: Optional[bool] = None  # dedus din pozitia numelui jucatorului si scor, vezi parse_recent_results


@dataclass
class MatchDetailData:
    player1: PlayerProfile = field(default_factory=PlayerProfile)
    player2: PlayerProfile = field(default_factory=PlayerProfile)
    surface_balance: dict[str, tuple[str, str]] = field(default_factory=dict)  # {"Clay": ("9/6", "6/6"), ...}
    player1_recent: list[RecentMatch] = field(default_factory=list)
    player2_recent: list[RecentMatch] = field(default_factory=list)
    h2h_exists: bool = False
    h2h_matches: list[RecentMatch] = field(default_factory=list)  # gol daca h2h_exists=False


def fetch_match_detail_html(match_id: int, timeout: float = 15.0) -> str | None:
    """Fetch simplu prin requests - CONFIRMAT server-rendered (2026-09-15),
    nu are nevoie de Selenium."""
    url = MATCH_DETAIL_URL.format(match_id=match_id)
    try:
        resp = _session.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as exc:
        logger.warning("fetch_match_detail_html: request failed for match_id=%s: %s", match_id, exc)
        return None


def find_match_id_from_gamedetail_link(href: str) -> int | None:
    """Extrage id-ul din href-ul unui link gasit in table.gamedetail de pe
    pagina unui jucator (ex. "/match-detail/?id=3323237" -> 3323237)."""
    m = re.search(r"[?&]id=(\d+)", href)
    return int(m.group(1)) if m else None


def _row_cells_text(row) -> list[str]:
    return [c.get_text(strip=True) for c in row.find_all(["td", "th"])]


def parse_player_profiles(soup: BeautifulSoup) -> tuple[PlayerProfile, PlayerProfile]:
    """Parseaza table.gDetail. CONFIRMAT (2026-09-15, dump celula-cu-celula):
    randurile au celule GOALE intercalate (ex. randul de ranking are 5 celule
    brute: ['', '30.', 'Singles ranking', '60.', '']) - se filtreaza goale
    intai, apoi se asteapta exact 3 valori [val1, eticheta, val2]. Randul de
    header are 3 celule brute cu mijlocul gol: ['Parry Diane', '', 'Stearns Peyton']."""
    p1, p2 = PlayerProfile(), PlayerProfile()
    table = soup.find("table", class_="gDetail")
    if table is None:
        return p1, p2

    rows = table.find_all("tr")
    if not rows:
        return p1, p2

    header_cells = [c for c in _row_cells_text(rows[0]) if c]
    if len(header_cells) >= 2:
        p1.name, p2.name = header_cells[0], header_cells[-1]

    _field_map = {
        "singles ranking": "ranking",
        "birthdate": "birthdate",
        "height": "height",
        "weight": "weight",
        "plays": "plays",
        "turned pro": "turned_pro",
    }
    for row in rows[1:]:
        cells = [c for c in _row_cells_text(row) if c]
        if len(cells) != 3:
            continue
        val1, label, val2 = cells
        attr = _field_map.get(label.strip().lower())
        if attr:
            setattr(p1, attr, val1 or None)
            setattr(p2, attr, val2 or None)

    return p1, p2


def parse_surface_balance(soup: BeautifulSoup) -> dict[str, tuple[str, str]]:
    """Parseaza primul table.balance de pe match-detail (cel cu coloane
    Suprafata/P1/P2, NU cel cu randuri de an - acela apare mai jos pe
    pagina si are alt format, cu "Year" in loc de "Surface" ca prim header)."""
    result: dict[str, tuple[str, str]] = {}
    for table in soup.find_all("table", class_="balance"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header = _row_cells_text(rows[0])
        if not header or header[0].strip().lower() != "surface":
            continue  # e tabelul cu "Year", nu cel cu "Surface" - sarim peste
        for row in rows[1:]:
            cells = _row_cells_text(row)
            if len(cells) == 3:
                surface, v1, v2 = cells
                result[surface] = (v1, v2)
        break  # doar primul tabel "Surface" ne intereseaza aici
    return result


def _parse_mutual_table(table) -> list[RecentMatch]:
    """Parseaza un table.mutual - istoricul recent de meciuri al unui
    jucator. CONFIRMAT (2026-09-15, dump celula-cu-celula): fiecare meci
    ocupa 2 randuri <tr> consecutive:
    - randul 1: o singura celula cu "Turneu,Runda, Data" (ex.
      "US Open,2R, 02.09.2026") - de separat prin virgula
    - randul 2: celula goala + "NumeA-NumeB" + "Scor" (ex.
      ["", "Cirstea-Parry", "2:0"])
    Ordinea NUeste intotdeauna acelasi jucator primul - "Cirstea-Parry" vs
    "Parry-Golubic" arata ca jucatorul urmarit apare cand in stanga, cand in
    dreapta. NU presupunem cine a castigat doar din pozitie - opponent ramane
    text brut "NumeA-NumeB", de interpretat ulterior cu numele jucatorului
    cunoscut daca e nevoie de won/lost."""
    matches: list[RecentMatch] = []
    rows = table.find_all("tr")
    i = 0
    while i < len(rows) - 1:
        header_cells = [c for c in _row_cells_text(rows[i]) if c]
        if not header_cells:
            i += 1
            continue
        parts = [p.strip() for p in header_cells[0].split(",")]
        tournament = parts[0] if len(parts) > 0 else ""
        round_ = parts[1] if len(parts) > 1 else ""
        date = parts[2] if len(parts) > 2 else ""

        detail_cells = [c for c in _row_cells_text(rows[i + 1]) if c]
        if len(detail_cells) >= 2:
            matches.append(RecentMatch(
                tournament=tournament,
                round=round_,
                date=date,
                opponent=detail_cells[0],
                score=detail_cells[1],
            ))
        i += 2
    return matches


def parse_recent_results(soup: BeautifulSoup) -> tuple[list[RecentMatch], list[RecentMatch]]:
    """Parseaza cele doua table.mutual - primul = jucator 1, al doilea =
    jucator 2 (ordinea CONFIRMATA prin inspectia Parry/Stearns: primul bloc
    continea numai meciuri cu "Parry", al doilea numai cu "Stearns")."""
    tables = soup.find_all("table", class_="mutual")
    p1_matches = _parse_mutual_table(tables[0]) if len(tables) > 0 else []
    p2_matches = _parse_mutual_table(tables[1]) if len(tables) > 1 else []
    return p1_matches, p2_matches


def parse_h2h(soup: BeautifulSoup) -> tuple[bool, list[RecentMatch]]:
    """Verifica daca exista H2H real intre cei doi jucatori ai meciului.
    CONFIRMAT: cand nu exista, apare div.no-data cu "No head-to-head record."
    NEconfirmat: structura exacta a tabelului cand H2H CHIAR exista - nu am
    testat inca o pereche cu istoric comun. Rescrie partea "else" de mai jos
    dupa ce gasesti un meci intre doi jucatori cu H2H real."""
    no_data = soup.find("div", class_="no-data")
    if no_data and "head-to-head" in no_data.get_text(strip=True).lower():
        return False, []

    head_div = soup.find("div", class_="head")
    if head_div is None:
        return False, []

    return True, []


def parse_match_detail(html: str) -> MatchDetailData:
    soup = BeautifulSoup(html, "lxml")
    data = MatchDetailData()
    data.player1, data.player2 = parse_player_profiles(soup)
    data.surface_balance = parse_surface_balance(soup)
    data.player1_recent, data.player2_recent = parse_recent_results(soup)
    data.h2h_exists, data.h2h_matches = parse_h2h(soup)
    return data


def fetch_and_parse_match(match_id: int) -> MatchDetailData | None:
    html = fetch_match_detail_html(match_id)
    if html is None:
        return None
    return parse_match_detail(html)


# ============================================================
# Programul zilnic (pentru a lega meciurile Superbet de match_id-uri
# TennisExplorer prin potrivire de nume)
# ============================================================

import datetime as _dt  # noqa: E402

DAILY_SCHEDULE_URL = BASE_URL + "/matches/"

# CONFIRMAT (2026-09-15) prin inspectie: /matches/?type=wta-single&year=..&month=..&day=..
# NEconfirmat: valorile exacte pentru alte tur-uri (challenger, itf-m/f etc.)
# - presupunere prin analogie cu "wta-single"/"atp-single", de verificat
# inainte de a te baza pe ele pentru altceva decat atp/wta.
TOUR_TYPE_MAP = {
    "atp": "atp-single",
    "wta": "wta-single",
    "challenger": "challenger-single",   # NEconfirmat
    "wta-125": "wta-single",             # NEconfirmat - posibil inclus in wta-single, posibil separat
    "itf-m": "itf-men-single",           # NEconfirmat
    "itf-f": "itf-women-single",         # NEconfirmat
}


@dataclass
class ScheduledMatch:
    tournament: str = ""
    time_text: str = ""
    player1: str = ""  # format TennisExplorer: "Nume P." (nume complet, initiala prenumelui)
    player2: str = ""
    match_id: Optional[int] = None
    odds_home: Optional[str] = None
    odds_away: Optional[str] = None


def fetch_daily_schedule(tour_type: str, date: "_dt.date", timeout: float = 15.0) -> list[ScheduledMatch]:
    """Fetch programul zilei pentru un tur TennisExplorer (ex. "wta-single").
    CONFIRMAT (2026-09-15) structura pentru wta-single: fiecare meci ocupa 2
    <tr> consecutive intr-un table.result (nu table.result.interesting):
    - rand 1: [ora, jucator1+link, ..., cota_H, cota_A, "info"+link match-detail]
    - rand 2: [jucator2+link, ...] (fara ora, fara link match-detail)
    Randurile de header de turneu (clasa distincta, cu link spre pagina
    turneului si coloanele "S 1 2 3 4 5 H2H H A") marcheaza inceputul unui
    grup nou - turneul se aplica tuturor meciurilor de dedesubt pana la
    urmatorul header."""
    url = DAILY_SCHEDULE_URL
    params = {"type": tour_type, "year": date.year, "month": f"{date.month:02d}", "day": f"{date.day:02d}"}
    try:
        resp = _session.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("fetch_daily_schedule: request failed for tour_type=%s date=%s: %s", tour_type, date, exc)
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    tables = [t for t in soup.find_all("table", class_="result") if t.get("class") == ["result"]]

    matches: list[ScheduledMatch] = []
    for table in tables:
        current_tournament = ""
        rows = table.find_all("tr")
        i = 0
        while i < len(rows):
            row = rows[i]
            cells = row.find_all(["td", "th"])
            cell_texts = [c.get_text(strip=True) for c in cells]

            # Rand de header de turneu: contine un link spre pagina turneului
            # (nu spre /player/ sau /match-detail/) - de obicei prima celula.
            tournament_link = None
            if cells:
                first_link = cells[0].find("a", href=True)
                if first_link and "/player/" not in first_link["href"] and "/match-detail/" not in first_link["href"]:
                    tournament_link = first_link
            if tournament_link is not None and cell_texts and cell_texts[0] not in ("", "info"):
                current_tournament = cell_texts[0]
                i += 1
                continue

            # Rand de meci (primul din pereche): are ora in prima celula
            # (format HH:MM) si un link match-detail pe ultima celula.
            match_link = None
            for c in cells:
                a = c.find("a", href=True)
                if a and "/match-detail/" in a["href"]:
                    match_link = a
                    break

            if match_link is not None and i + 1 < len(rows):
                time_text = cell_texts[0] if cell_texts and re.match(r"^\d{1,2}:\d{2}$", cell_texts[0]) else ""
                p1_link = row.find("a", href=re.compile(r"^/player/"))
                player1 = p1_link.get_text(strip=True) if p1_link else ""

                next_row = rows[i + 1]
                p2_link = next_row.find("a", href=re.compile(r"^/player/"))
                player2 = p2_link.get_text(strip=True) if p2_link else ""

                # Cotele sunt de obicei ultimele 2 valori numerice inainte de "info"
                odds_candidates = [t for t in cell_texts if re.match(r"^\d+\.\d+$", t)]
                odds_home = odds_candidates[0] if len(odds_candidates) > 0 else None
                odds_away = odds_candidates[1] if len(odds_candidates) > 1 else None

                match_id = find_match_id_from_gamedetail_link(match_link["href"])

                matches.append(ScheduledMatch(
                    tournament=current_tournament,
                    time_text=time_text,
                    player1=player1,
                    player2=player2,
                    match_id=match_id,
                    odds_home=odds_home,
                    odds_away=odds_away,
                ))
                i += 2
                continue

            i += 1

    return matches


def _normalize_name_for_matching(name: str) -> str:
    """Extrage numele de familie, lowercase, fara diacritice complexe -
    suficient pentru potrivire aproximativa intre formatul Superbet
    ("Diane Parry") si formatul TennisExplorer ("Parry D.")."""
    name = name.strip().lower()
    name = re.sub(r"[.\-']", " ", name)
    return " ".join(name.split())


def find_scheduled_match(
    superbet_player1: str,
    superbet_player2: str,
    schedule: list[ScheduledMatch],
) -> ScheduledMatch | None:
    """Potriveste un meci Superbet (nume complete: "Diane Parry") cu un
    ScheduledMatch de pe TennisExplorer (format "Parry D."), pe baza
    numelui de familie - heuristica, NU 100% garantata (nume de familie
    duble sau coincidente pot da rezultate gresite; de verificat manual
    rezultatele la inceput)."""
    def surname_tokens(full_name: str) -> set[str]:
        norm = _normalize_name_for_matching(full_name)
        return set(norm.split())

    sb_p1_tokens = surname_tokens(superbet_player1)
    sb_p2_tokens = surname_tokens(superbet_player2)

    for m in schedule:
        te_p1_tokens = surname_tokens(m.player1)
        te_p2_tokens = surname_tokens(m.player2)

        direct = (sb_p1_tokens & te_p1_tokens) and (sb_p2_tokens & te_p2_tokens)
        swapped = (sb_p1_tokens & te_p2_tokens) and (sb_p2_tokens & te_p1_tokens)
        if direct or swapped:
            return m

    return None
