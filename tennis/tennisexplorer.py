from __future__ import annotations

import logging

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import H2HStats, PlayerFormStats

logger = logging.getLogger(__name__)

# NEconfirmat — TennisExplorer.com e din aceeași familie de site-uri ca
# BetExplorer (probabil aceeași companie), dar structura paginii de JUCĂTOR
# nu a fost investigată deloc încă. Nu presupune că tiparul de "ts token +
# AJAX" de la BetExplorer (vezi betscraper/match_standings.py din proiectul
# [[bet]]) se aplică identic aici — tenisul are pagini per-jucător, nu
# clasamente pe ligă, deci mecanismul poate fi complet diferit. Rulează
# tools/inspect_page.py pe o pagină de jucător înainte de orice.
BASE_URL = "https://www.tennisexplorer.com"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_session = requests.Session()
_session.headers.update({"User-Agent": _USER_AGENT})
_retry = Retry(total=5, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504], respect_retry_after_header=True)
_session.mount("https://", HTTPAdapter(max_retries=_retry))
_session.mount("http://", HTTPAdapter(max_retries=_retry))


def find_player_url(player_name: str) -> str | None:
    """Caută un jucător pe TennisExplorer și întoarce URL-ul paginii lui.

    NEIMPLEMENTAT — placeholder. TennisExplorer are probabil o pagină de
    căutare (/search/?q=...) sau un slug previzibil din nume
    (/player/nume-prenume/), la fel ca BetExplorer cu echipele. De
    confirmat cu inspect_page.py înainte de a scrie logica de parsare.
    """
    raise NotImplementedError(
        "Investighează întâi structura TennisExplorer cu tools/inspect_page.py "
        "pe o pagină de jucător cunoscută, apoi implementează căutarea."
    )


def fetch_player_page(player_url: str, timeout: float = 15.0) -> str | None:
    """Fetch simplu prin requests — de confirmat dacă pagina de jucător e
    server-rendered (probabil da, ca și paginile de echipă de la
    BetExplorer) sau are nevoie de Selenium pentru vreo secțiune (ex.
    formă recentă încărcată via AJAX)."""
    try:
        resp = _session.get(player_url, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as exc:
        logger.warning("fetch_player_page: request failed for %s: %s", player_url, exc)
        return None


def parse_recent_form(html: str) -> PlayerFormStats:
    """NEIMPLEMENTAT — placeholder. Extrage ranking, formă recentă (ultimele
    5-10 meciuri, W/L), record pe suprafață din HTML-ul paginii de jucător.
    Selectorii exacți depind de structura reală, de descoperit."""
    soup = BeautifulSoup(html, "lxml")  # noqa: F841 — placeholder, nimic parsat încă
    return PlayerFormStats()


def fetch_h2h(player1_url: str, player2_url: str) -> H2HStats:
    """NEIMPLEMENTAT — placeholder. TennisExplorer are de obicei un tab/pagină
    dedicată H2H per pereche de jucători, sau H2H apare direct pe pagina
    meciului dacă se scrapuie de acolo în loc de pe pagina jucătorului — de
    decis odată ce structura reală e clară."""
    return H2HStats()
