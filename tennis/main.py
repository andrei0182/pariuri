"""Analiza meciuri de tenis: combina cotele Superbet cu statisticile de pe
TennisExplorer (rank, forma recenta, comparatie suprafata) intr-o estimare
compusa a sanselor de castig, comparata cu ce implica cota Superbet.

Estimarea compusa NU e un model predictiv validat statistic - e o medie
simpla intre probabilitatea implicita din rank (1/sqrt(rank) normalizat
intre cei doi jucatori) si probabilitatea implicita din rata de victorii
pe formă recentă. E gandita ca punct de plecare pentru propria analiza,
nu ca raspuns final. Coloana "Semnal" arata doar unde estimarea noastra
difera semnificativ (>7 puncte procentuale) de ce implica cota Superbet -
asta poate insemna fie ca am gasit ceva ce piata a ratat, fie (mai
probabil, mai ales la inceput) ca semnalele noastre simple (doar rank +
formă, fara accidentari/oboseala/conditii) sunt incomplete.

Din estimarea compusa (% castig meci), coloanele "% Estimare Minim 1 Set"
si "% Estimare Sub/Peste 2.5 Seturi" sunt DERIVATE matematic (nu masurate
direct), presupunand seturile independente cu aceeasi sansa per set
(simplificare standard, nu exacta - oboseala/momentum nu sunt modelate).
NU exista inca o estimare pentru "total game-uri per set" - ar necesita
scoruri detaliate pe game-uri din istoricul de meciuri, pe care nu le
avem (TennisExplorer ne da doar scorul final pe seturi, ex. "2:0").

Ce NU e inclus inca:
- accidentari (tabelul playerInjuries de pe pagina de jucator exista, dar
  nu e inca legat in acest flux)
- calitatea adversarilor din forma recenta (TennisExplorer nu da rank-ul
  adversarului in lista de meciuri recente)
- Cupa Davis / Billie Jean King Cup / United Cup (competitii pe echipe,
  structura de pagina diferita pe TennisExplorer)
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import re
import time

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from tenis_scraper import events, tennisexplorer, tournaments

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

SUPPORTED_TOURS = ("atp", "wta", "challenger", "wta-125", "itf-m", "itf-f", "utr-m", "utr-f")


def _recent_summary(matches: list[tennisexplorer.RecentMatch], limit: int = 10) -> str:
    parts = []
    for m in matches[:limit]:
        mark = {"True": "V", "False": "I", "None": "?"}[str(m.won)]
        parts.append(f"[{mark}] {m.tournament} {m.round} ({m.date}): {m.opponent} {m.score}")
    return " | ".join(parts) if parts else ""


def _parse_recent_match_date(m: tennisexplorer.RecentMatch) -> dt.date | None:
    """Extrage data unui meci din istoricul recent (format TennisExplorer
    "DD.MM.YYYY"). CONFIRMAT (2026-09-22): la meciurile din campionate pe
    echipe (ex. Bundesliga, Swiss Nationalliga), celula bruta are doar 2
    parti separate prin virgula ("Turneu,Data"), nu 3 ("Turneu,Runda,Data")
    ca la turneele individuale - data ajunge in campul `round`, nu `date`
    (vezi _parse_mutual_table). Incercam `date` intai, apoi `round` ca
    fallback, altfel ratam exact meciurile dese (indicator de oboseala) la
    jucatorii care joaca si in campionate pe echipe intre turnee."""
    for raw in (m.date, m.round):
        if not raw:
            continue
        match = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", raw.strip())
        if not match:
            continue
        day, month, year = (int(g) for g in match.groups())
        try:
            return dt.date(year, month, day)
        except ValueError:
            continue
    return None


def _matches_played_within(
    recent: list[tennisexplorer.RecentMatch], reference_date: dt.date, window_days: int = 3
) -> int:
    """Numara cate meciuri din istoricul recent au data in fereastra de
    `window_days` zile incheiata la `reference_date` (inclusiv ziua
    meciului curent) - folosit ca proxy pentru oboseala (meciuri
    consecutive), nu masoara durata/intensitatea lor."""
    start = reference_date - dt.timedelta(days=window_days - 1)
    return sum(
        1
        for m in recent
        if (d := _parse_recent_match_date(m)) is not None and start <= d <= reference_date
    )


# Puncte procentuale scazute din estimarea compusa a jucatorului in functie
# de cate meciuri a jucat in ultimele 3 zile - CONFIRMAT (2026-09-22, cu
# Andrei): motivat de recomandarea gresita pe Rodriguez Taverna vs Boscardin
# Dias (2026-09-22), unde Taverna avea forma recenta puternica (6V-4I) doar
# pentru ca tocmai castigase 2 calificari in 2 zile, dar a pierdut categoric
# in turul 1 - obosit dupa al 3-lea meci in 3 zile impotriva unui adversar
# odihnit si mai bine clasat. Praguri alese empiric (nu calibrate
# statistic), ca punct de plecare - de rafinat daca se dovedesc gresite.
_FATIGUE_PENALTY_TABLE_PP = {0: 0.0, 1: 3.0, 2: 6.0}
_FATIGUE_PENALTY_PP_MAX = 10.0  # 3+ meciuri in ultimele 3 zile


def _fatigue_penalty_pp(matches_last_3d: int) -> float:
    return _FATIGUE_PENALTY_TABLE_PP.get(matches_last_3d, _FATIGUE_PENALTY_PP_MAX)


def _parse_rank(rank_str: str | None) -> int | None:
    """Rank-ul vine ca text de pe TennisExplorer, ex. "169.", "-." (fara
    clasament). Curatam punctul final si convertim la int, None daca nu
    exista clasament."""
    if not rank_str:
        return None
    s = rank_str.strip().rstrip(".")
    try:
        val = int(s)
        return val if val > 0 else None
    except ValueError:
        return None


UNRANKED_FALLBACK = 2000  # presupunere pentru jucatori fara clasament, doar pentru scor relativ


def _rank_probability(rank1: int | None, rank2: int | None) -> float | None:
    """Probabilitate relativa bazata DOAR pe clasament, normalizata intre
    cei doi jucatori. Foloseste 1/sqrt(rank) in loc de 1/rank brut - 1/rank
    da valori nerealist de extreme la diferente mari (ex. rank 5 vs 200 ar
    da ~97.6% cu 1/rank, quando in tenis chiar si un favorit clar pastreaza
    o sansa realista pentru underdog). Tot o aproximare bruta, dar mai
    temperata.
    CONFIRMAT (2026-09-17, cu Andrei): daca AMBII jucatori sunt fara rang
    (comun la juniori/futures/ITF), returnam None in loc de a cadea pe
    UNRANKED_FALLBACK pentru amandoi, care ar da mereu exact 50% - o
    valoare falsa care intra in estimarea compusa cu pondere completa, ca
    si cum ar fi un semnal real, trage estimarea spre egalitate exact la
    meciurile unde piata e cel mai sigura de un favorit (cote foarte
    asimetrice) si a produs zeci de "edge"-uri false in raportul din
    2026-09-17 (110 recomandari din 203 meciuri, multe cu favoriti
    zdrobitori la cota 1.0-1.01)."""
    if rank1 is None and rank2 is None:
        return None
    r1 = rank1 if rank1 is not None else UNRANKED_FALLBACK
    r2 = rank2 if rank2 is not None else UNRANKED_FALLBACK
    score1, score2 = 1.0 / (r1 ** 0.5), 1.0 / (r2 ** 0.5)
    total = score1 + score2
    return score1 / total if total > 0 else None


def _form_probability(w1: int, l1: int, w2: int, l2: int) -> float | None:
    """Probabilitate relativa bazata pe rata de victorii din formă recentă
    (nu neaparat impotriva acelorasi adversari) - semnal slab de volatilitate
    pe termen scurt, nu o statistica riguroasa."""
    t1, t2 = w1 + l1, w2 + l2
    if t1 == 0 or t2 == 0:
        return None
    rate1, rate2 = w1 / t1, w2 / t2
    total = rate1 + rate2
    if total == 0:
        return None
    return rate1 / total


FORM_DECAY = 0.85  # ponderea scade cu 15% la fiecare meci mai vechi (lista e cea mai recenta prima)


def _weighted_form(matches: list[tennisexplorer.RecentMatch], decay: float = FORM_DECAY) -> tuple[float, float]:
    """Victorii/infrangeri ponderate dupa recenta: meciul cel mai recent
    conteaza 1.0, urmatorul 0.85, apoi 0.72... Meciurile ambigue (won=None)
    sunt sarite fara sa consume o pozitie. Intrare pentru _form_probability."""
    wins = losses = 0.0
    weight = 1.0
    for m in matches:
        if m.won is None:
            continue
        if m.won:
            wins += weight
        else:
            losses += weight
        weight *= decay
    return wins, losses


def _implied_probability(odds1: float, odds2: float) -> float | None:
    """Probabilitate implicita din cotele Superbet, normalizata ca sa
    elimine marja casei (suma 1/cota1 + 1/cota2 e de obicei >1)."""
    if not odds1 or not odds2:
        return None
    inv1, inv2 = 1.0 / odds1, 1.0 / odds2
    total = inv1 + inv2
    return inv1 / total if total > 0 else None


def _parse_record(text: str | None) -> tuple[int, int] | None:
    """Parseaza 'W/L' (ex. '9/6') intr-un tuplu de int-uri; None daca gol/invalid."""
    if not text or text == "-":
        return None
    match = re.match(r"(\d+)/(\d+)", text.strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _career_rating_probability(
    balance: dict[str, tuple[str, str]]
) -> tuple[float | None, float]:
    """Combina recordul pe toate suprafetele (deja extras in surface_balance,
    fara niciun fetch suplimentar) intr-o probabilitate relativa P1 vs P2,
    plus un scor de incredere (0-1) bazat pe volumul total de meciuri
    disponibile pentru cei doi jucatori. Incredere mica (putine meciuri
    combinate) inseamna ca semnalul asta conteaza mai putin in estimarea
    finala - vezi ponderea aplicata in _composite_estimate."""
    total_w1 = total_l1 = total_w2 = total_l2 = 0
    for v1_str, v2_str in balance.values():
        rec1 = _parse_record(v1_str)
        rec2 = _parse_record(v2_str)
        if rec1:
            total_w1 += rec1[0]
            total_l1 += rec1[1]
        if rec2:
            total_w2 += rec2[0]
            total_l2 += rec2[1]

    t1, t2 = total_w1 + total_l1, total_w2 + total_l2
    if t1 == 0 or t2 == 0:
        return None, 0.0

    rate1, rate2 = total_w1 / t1, total_w2 / t2
    total = rate1 + rate2
    prob1 = rate1 / total if total > 0 else None

    # satureaza la ~40 de meciuri combinate intre cei doi jucatori
    confidence = min((t1 + t2) / 40, 1.0)
    return prob1, confidence


SURFACE_PRIOR_MATCHES = 5  # cat de mult tragem recordul pe suprafata spre recordul general


def _log5(rate1: float, rate2: float) -> float | None:
    """Probabilitatea ca jucatorul 1 sa-l bata pe 2 din ratele lor de victorie
    (formula log5 a lui Bill James) - mai corecta decat rate1/(rate1+rate2)
    la rate extreme."""
    num = rate1 * (1 - rate2)
    den = num + rate2 * (1 - rate1)
    return num / den if den > 0 else None


def _surface_rating_probability(
    balance: dict[str, tuple[str, str]], surface: str
) -> tuple[float | None, float]:
    """Semnal de rating pe SUPRAFATA MECIULUI (nu suma pe toate suprafetele,
    cum facea _career_rating_probability): recordul fiecarui jucator pe
    suprafata respectiva, tras spre recordul lui general cu
    SURFACE_PRIOR_MATCHES meciuri "virtuale" (un 3/0 pe iarba nu inseamna
    100%). Recordurile din tabel sunt pe sezonul curent. Daca suprafata e
    necunoscuta, cade pe _career_rating_probability. Incredere: volumul de
    meciuri pe suprafata al celor doi, saturat la 20."""
    record = next((v for k, v in balance.items() if k.lower() == surface.lower()), None) if surface else None
    if record is None:
        return _career_rating_probability(balance)

    rates = []
    surface_matches = 0
    for idx in (0, 1):
        overall_w = overall_l = 0
        for values in balance.values():
            rec = _parse_record(values[idx])
            if rec:
                overall_w += rec[0]
                overall_l += rec[1]
        if overall_w + overall_l == 0:
            return None, 0.0
        overall_rate = overall_w / (overall_w + overall_l)
        surf = _parse_record(record[idx]) or (0, 0)
        surface_matches += surf[0] + surf[1]
        rates.append((surf[0] + SURFACE_PRIOR_MATCHES * overall_rate) / (surf[0] + surf[1] + SURFACE_PRIOR_MATCHES))

    return _log5(rates[0], rates[1]), min(surface_matches / 20, 1.0)


H2H_SAME_SURFACE_WEIGHT = 1.5
H2H_YEARLY_DECAY = 0.8
H2H_MAX_WEIGHT = 0.5  # H2H conteaza cel mult cat jumatate din rank sau formă


def _h2h_probability(
    h2h: list[tennisexplorer.H2HMatch],
    player1_name: str,
    surface: str,
    current_year: int,
    exclude_match_id: int | None = None,
) -> tuple[float | None, float]:
    """Semnal din meciurile directe: fiecare victorie cantareste 1, x1.5 pe
    aceeasi suprafata cu meciul de azi, x0.8 pentru fiecare an vechime.
    Probabilitate cu Laplace (+1/+2), ca 1-0 sa nu insemne 100%. Ponderea
    in estimarea compusa creste cu numarul de meciuri, pana la H2H_MAX_WEIGHT
    de la 4 meciuri (ponderate) in sus. Meciul curent (exclude_match_id) e
    sarit - dupa ce s-a jucat apare si el in tabel."""
    p1_tokens = tennisexplorer._surname_tokens_from_profile_name(player1_name)
    wins1 = total = 0.0
    for m in h2h:
        if exclude_match_id is not None and m.match_id == exclude_match_id:
            continue
        weight = H2H_SAME_SURFACE_WEIGHT if surface and m.surface.lower() == surface.lower() else 1.0
        if m.year is not None:
            weight *= H2H_YEARLY_DECAY ** max(current_year - m.year, 0)
        total += weight
        if set(m.winner.lower().split()) & p1_tokens:
            wins1 += weight
    if total == 0:
        return None, 0.0
    return (wins1 + 1) / (total + 2), H2H_MAX_WEIGHT * min(total / 4, 1.0)


def _composite_estimate(
    rank_p: float | None,
    form_p: float | None,
    rating_p: float | None = None,
    rating_confidence: float = 0.0,
    h2h_p: float | None = None,
    h2h_weight: float = 0.0,
) -> float | None:
    """Medie ponderata a semnalelor disponibile (rank + formă + rating de
    carieră pe suprafață). Rank si formă au pondere fixa 1.0 fiecare;
    rating-ul de cariera e ponderat de propria lui incredere, ca sa nu
    distorsioneze estimarea cand avem putine date pentru ele. NU e un model
    predictiv validat, doar o combinare simpla a semnalelor pe care le avem -
    de tratat ca punct de plecare pentru propria ta analiza, nu ca raspuns
    final. CONFIRMAT (2026-09-17, cu Andrei): daca AMBELE semnale rank si
    formă lipsesc, returnam None chiar daca ratingul de cariera exista -
    un rating bazat doar pe win-rate general (fara ajustare dupa calitatea
    adversarilor) nu e suficient de fiabil ca semnal unic, mai ales la
    meciuri cu decalaj mare de nivel intre jucatori (unde da estimari
    apropiate de 50% chiar daca unul e un favorit clar)."""
    if rank_p is None and form_p is None:
        return None

    weighted_sum = 0.0
    weight_total = 0.0
    if rank_p is not None:
        weighted_sum += rank_p * 1.0
        weight_total += 1.0
    if form_p is not None:
        weighted_sum += form_p * 1.0
        weight_total += 1.0
    if rating_p is not None and rating_confidence > 0:
        weighted_sum += rating_p * rating_confidence
        weight_total += rating_confidence
    if h2h_p is not None and h2h_weight > 0:
        weighted_sum += h2h_p * h2h_weight
        weight_total += h2h_weight
    if weight_total == 0:
        return None
    return weighted_sum / weight_total


def _signal_label(composite_p1: float | None, implied_p1: float | None, threshold: float = 0.07) -> str:
    if composite_p1 is None or implied_p1 is None:
        return "Date insuficiente"
    diff = composite_p1 - implied_p1
    if diff > threshold:
        return f"Posibil value pe J1 (+{diff*100:.0f}pp vs piata)"
    if diff < -threshold:
        return f"Posibil value pe J2 (+{-diff*100:.0f}pp vs piata)"
    return "Aliniat cu piata"


def _solve_set_win_prob(match_win_prob: float) -> float:
    """Deriva probabilitatea de castig a UNUI SET (s) din probabilitatea
    de castig a MECIULUI (p), presupunand seturile independente si cu
    aceeasi sansa s per set (simplificare standard in analiza sportiva,
    NU o masuratoare directa - meciul e best-of-3, deci:
    p = P(castiga 2-0) + P(castiga 2-1) = s^2 + 2*s^2*(1-s) = 3s^2 - 2s^3
    Functia e monotona crescatoare pe [0,1], deci inversam prin bisectie."""
    if match_win_prob <= 0:
        return 0.0
    if match_win_prob >= 1:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(50):
        mid = (lo + hi) / 2
        p_mid = 3 * mid ** 2 - 2 * mid ** 3
        if p_mid < match_win_prob:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _derived_set_probabilities(match_win_prob_p1: float) -> dict:
    """Din probabilitatea de castig a meciului (J1), calculeaza probabilitati
    DERIVATE (nu masurate direct) pentru minim-1-set si total-seturi,
    folosind modelul seturi-independente de mai sus. Aceeasi simplificare
    ca la orice model sportiv de baza - presupune ca fiecare set e un
    experiment Bernoulli independent cu aceeasi sansa s, ceea ce in
    realitate nu e mereu adevarat (oboseala, momentum), dar e un punct de
    plecare rezonabil fara date suplimentare (scoruri pe game-uri per set
    din istoric, pe care nu le avem inca)."""
    s = _solve_set_win_prob(match_win_prob_p1)
    return {
        "set_win_prob_p1": s,
        "min1set_p1": 1 - (1 - s) ** 2,
        "min1set_p2": 1 - s ** 2,
        "total_sets_under": s ** 2 + (1 - s) ** 2,   # meciul se termina 2-0 (2 seturi)
        "total_sets_over": 2 * s * (1 - s),           # meciul merge la 3 seturi
    }


def _h2h_summary(h2h: list[tennisexplorer.H2HMatch], exclude_match_id: int | None) -> str:
    """Ex. "Baez 2-0 (2026 Rome Clay 6-3 7-6; 2026 Auckland Hard 7-5 6-0)"."""
    past = [m for m in h2h if m.match_id is None or m.match_id != exclude_match_id]
    wins: dict[str, int] = {}
    for m in past:
        wins[m.winner] = wins.get(m.winner, 0) + 1
    tally = ", ".join(f"{name} {n}" for name, n in sorted(wins.items(), key=lambda kv: -kv[1]))
    details = "; ".join(
        f"{m.year} {m.tournament} {m.surface} {m.winner} " + " ".join(f"{a}-{b}" for a, b in m.sets)
        for m in past
    )
    return f"{tally} ({details})"


def _surface_summary(balance: dict[str, tuple[str, str]]) -> str:
    parts = [f"{surface}: {v1} vs {v2}" for surface, (v1, v2) in balance.items()]
    return " | ".join(parts) if parts else ""


def _fetch_schedule_cached(te_type: str, date: dt.date, cache: dict) -> list[tennisexplorer.ScheduledMatch]:
    """Mai multe tur-uri Superbet (ex. challenger, itf-m, utr-m) mapeaza pe
    acelasi te_type ("atp-single") - evitam fetch-uri repetate ale aceleiasi
    pagini in cadrul aceleiasi rulari."""
    if te_type not in cache:
        schedule = tennisexplorer.fetch_daily_schedule(te_type, date)
        schedule += tennisexplorer.fetch_daily_schedule(te_type, date + dt.timedelta(days=1))
        schedule = [m for m in schedule if "/" not in m.player1 and "/" not in m.player2]
        cache[te_type] = schedule
    return cache[te_type]


def build_report(
    date: dt.date,
    tours: tuple[str, ...] = SUPPORTED_TOURS,
    te_delay: float = 1.0,
    extended_odds: bool = False,
) -> pd.DataFrame:
    rows: list[dict] = []
    schedule_cache: dict[str, list[tennisexplorer.ScheduledMatch]] = {}

    for tour in tours:
        tour_ids = tournaments.all_tennis_tournament_ids(tours=(tour,))
        logger.info("Tur %s: %d turnee gasite in mapping-ul Superbet", tour, len(tour_ids))
        if not tour_ids:
            continue

        raw_events = events.fetch_events_for_all_tournaments(tour_ids, date)
        sb_matches = [events.parse_event(e, tour=tour) for e in raw_events]
        # exclude dublu / meciuri fara cote (cel mai probabil deja jucate/anulate)
        sb_matches = [m for m in sb_matches if m.odds_winner.player1 and m.odds_winner.player2]
        # excludem dublu - "/" in nume produce potriviri false la matching-ul dupa nume de familie
        sb_matches = [m for m in sb_matches if "/" not in m.player1 and "/" not in m.player2]
        logger.info("Tur %s: %d meciuri simplu Superbet cu cote gasite pentru %s", tour, len(sb_matches), date)

        te_type = tennisexplorer.TOUR_TYPE_MAP.get(tour)
        if te_type is None:
            logger.warning("Tur %s: nu are mapping catre TennisExplorer, sarim peste stats", tour)
            schedule = []
        else:
            # CONFIRMAT (2026-09-16): meciurile Superbet din ultimele ore UTC
            # ale zilei (ex. 23:00) pot cadea deja pe "ziua urmatoare" in
            # calendarul local (CET/CEST) al TennisExplorer - luam si ziua+1
            # ca sa nu pierdem acele meciuri. Nu am vazut nevoie de ziua-1
            # (orele foarte devreme UTC raman pe aceeasi zi locala TE, fiind
            # inaintea UTC, nu in urma).
            schedule = _fetch_schedule_cached(te_type, date, schedule_cache)
            logger.info("Tur %s: %d meciuri simplu gasite in programul TennisExplorer (te_type=%s, ziua + ziua urmatoare)", tour, len(schedule), te_type)

        for sb_match in sb_matches:
            row = {
                "tour": tour,
                "tournament": sb_match.tournament or "",
                "time": sb_match.time_text,
                "player1": sb_match.player1,
                "player2": sb_match.player2,
                "odds_1": sb_match.odds_winner.player1,
                "odds_2": sb_match.odds_winner.player2,
                "match_url": sb_match.match_url,
                "te_match_id": None,
                "p1_ranking": None,
                "p2_ranking": None,
                "surface": "",
                "surface_comparison": "",
                "p1_form_summary": "",
                "p2_form_summary": "",
                "implied_prob_1": None,
                "implied_prob_2": None,
                "composite_prob_1": None,
                "composite_prob_2": None,
                "rating_confidence": None,
                "p1_matches_last_3d": None,
                "p2_matches_last_3d": None,
                "fatigue_adj_pp": None,
                "signal": "Date insuficiente",
                "our_min1set_p1": None,
                "our_min1set_p2": None,
                "our_total_sets_under": None,
                "our_total_sets_over": None,
                "p1_recent_form": "",
                "p2_recent_form": "",
                "h2h": "Neverificat",
                "odds_min1set_p1": None,
                "odds_min1set_p2": None,
                "odds_total_sets_line": None,
                "odds_total_sets_under": None,
                "odds_total_sets_over": None,
                "odds_set1_games": "",
                "odds_p1_games_min_line": None,
                "odds_p1_games_min_line_over": None,
                "odds_p2_games_min_line": None,
                "odds_p2_games_min_line_over": None,
            }

            implied_p1 = _implied_probability(sb_match.odds_winner.player1, sb_match.odds_winner.player2)
            if implied_p1 is not None:
                row["implied_prob_1"] = round(implied_p1 * 100, 1)
                row["implied_prob_2"] = round((1 - implied_p1) * 100, 1)

            if extended_odds and sb_match.event_id is not None:
                time.sleep(te_delay)
                ext = events.fetch_and_parse_extended_markets(sb_match.event_id, sb_match.player1, sb_match.player2)
                if ext is not None:
                    row["odds_min1set_p1"] = ext.min_1_set.player1_yes
                    row["odds_min1set_p2"] = ext.min_1_set.player2_yes
                    row["odds_total_sets_line"] = ext.total_sets.line
                    row["odds_total_sets_under"] = ext.total_sets.under
                    row["odds_total_sets_over"] = ext.total_sets.over
                    set1_lines = [sg for sg in ext.set_games if sg.set_number == 1]
                    row["odds_set1_games"] = " | ".join(
                        f"{sg.line}: Sub={sg.under} Peste={sg.over}" for sg in sorted(set1_lines, key=lambda x: x.line)
                    )

                    # CONFIRMAT (2026-09-18, cu Andrei): linia fixa (initial 3.5,
                    # apoi 4.5) de "total game-uri per jucator" nu e disponibila
                    # la toate meciurile - variaza de la meci la meci (ex. Kylie
                    # Collins avea minim 6.5, nu 4.5). Luam CEA MAI MICA linie
                    # disponibila pentru fiecare jucator, indiferent de valoare -
                    # asta confirma ca market-ul exista pentru meciul respectiv,
                    # fara sa ratam meciuri doar pentru ca bookmaker-ul a pornit
                    # de la o linie mai mare.
                    p1_games_lines = ext.player_total_games.get(sb_match.player1, [])
                    p2_games_lines = ext.player_total_games.get(sb_match.player2, [])
                    p1_min_line = min(p1_games_lines, key=lambda pg: pg.line, default=None)
                    p2_min_line = min(p2_games_lines, key=lambda pg: pg.line, default=None)
                    row["odds_p1_games_min_line"] = p1_min_line.line if p1_min_line else None
                    row["odds_p1_games_min_line_over"] = p1_min_line.over if p1_min_line else None
                    row["odds_p2_games_min_line"] = p2_min_line.line if p2_min_line else None
                    row["odds_p2_games_min_line_over"] = p2_min_line.over if p2_min_line else None

            match_found = tennisexplorer.find_scheduled_match(sb_match.player1, sb_match.player2, schedule)
            scheduled, swapped = match_found if match_found is not None else (None, False)
            if scheduled is not None and scheduled.match_id is not None:
                row["te_match_id"] = scheduled.match_id
                time.sleep(te_delay)  # nu bombarda serverul TennisExplorer
                detail = tennisexplorer.fetch_and_parse_match(scheduled.match_id)
                if detail is not None:
                    if swapped:
                        # TennisExplorer avea player1/player2 in ordine inversa
                        # fata de Superbet (vezi nota din find_scheduled_match) -
                        # interschimbam TOATE datele din detail inainte sa le
                        # folosim, altfel rank/forma/rating ajung atribuite
                        # jucatorului gresit si recomandarea poate iesi inversata.
                        detail.player1, detail.player2 = detail.player2, detail.player1
                        detail.player1_recent, detail.player2_recent = (
                            detail.player2_recent, detail.player1_recent,
                        )
                        detail.surface_balance = {
                            surface: (v2, v1) for surface, (v1, v2) in detail.surface_balance.items()
                        }
                    row["p1_ranking"] = detail.player1.ranking
                    row["p2_ranking"] = detail.player2.ranking
                    row["surface_comparison"] = _surface_summary(detail.surface_balance)
                    row["p1_form_summary"] = tennisexplorer.summarize_form(detail.player1_recent)
                    row["p2_form_summary"] = tennisexplorer.summarize_form(detail.player2_recent)
                    row["p1_recent_form"] = _recent_summary(detail.player1_recent)
                    row["p2_recent_form"] = _recent_summary(detail.player2_recent)
                    row["h2h"] = (
                        "Exista istoric H2H (detalii de verificat manual pe match_url)"
                        if detail.h2h_exists else "Fara istoric H2H"
                    )

                    rank1, rank2 = _parse_rank(detail.player1.ranking), _parse_rank(detail.player2.ranking)
                    w1, l1 = _weighted_form(detail.player1_recent)
                    w2, l2 = _weighted_form(detail.player2_recent)

                    rank_p1 = _rank_probability(rank1, rank2)
                    form_p1 = _form_probability(w1, l1, w2, l2)
                    rating_p1, rating_confidence = _surface_rating_probability(detail.surface_balance, detail.surface)
                    h2h_p1, h2h_weight = _h2h_probability(
                        detail.h2h_matches, detail.player1.name, detail.surface, date.year,
                        exclude_match_id=scheduled.match_id,
                    )
                    composite_p1 = _composite_estimate(
                        rank_p1, form_p1, rating_p1, rating_confidence, h2h_p1, h2h_weight,
                    )
                    row["rating_confidence"] = round(rating_confidence, 2)
                    row["surface"] = detail.surface
                    if h2h_p1 is not None:
                        row["h2h"] = _h2h_summary(detail.h2h_matches, scheduled.match_id)

                    if composite_p1 is not None:
                        # Ajustare oboseala - scade din estimarea jucatorului
                        # mai obosit (mai multe meciuri in ultimele 3 zile),
                        # NU intra in media ponderata cu rank/forma/rating
                        # fiindca nu e o probabilitate proprie, ci un discount
                        # aplicat DUPA. Vezi nota de la _FATIGUE_PENALTY_TABLE_PP.
                        n1_last3d = _matches_played_within(detail.player1_recent, date)
                        n2_last3d = _matches_played_within(detail.player2_recent, date)
                        fatigue_adj_pp = _fatigue_penalty_pp(n2_last3d) - _fatigue_penalty_pp(n1_last3d)
                        composite_p1 = min(max(composite_p1 + fatigue_adj_pp / 100, 0.0), 1.0)
                        row["p1_matches_last_3d"] = n1_last3d
                        row["p2_matches_last_3d"] = n2_last3d
                        row["fatigue_adj_pp"] = round(fatigue_adj_pp, 1)

                        row["composite_prob_1"] = round(composite_p1 * 100, 1)
                        row["composite_prob_2"] = round((1 - composite_p1) * 100, 1)
                        row["signal"] = _signal_label(composite_p1, implied_p1)

                        derived = _derived_set_probabilities(composite_p1)
                        row["our_min1set_p1"] = round(derived["min1set_p1"] * 100, 1)
                        row["our_min1set_p2"] = round(derived["min1set_p2"] * 100, 1)
                        row["our_total_sets_under"] = round(derived["total_sets_under"] * 100, 1)
                        row["our_total_sets_over"] = round(derived["total_sets_over"] * 100, 1)
            else:
                logger.info("Nu am gasit potrivire TennisExplorer pentru: %s vs %s", sb_match.player1, sb_match.player2)

            rows.append(row)

    return pd.DataFrame(rows)


_COLUMN_LABELS = {
    "tour": "Tur", "tournament": "Turneu", "time": "Ora",
    "player1": "Jucător 1", "player2": "Jucător 2",
    "odds_1": "Cotă 1", "odds_2": "Cotă 2", "match_url": "Link Superbet",
    "te_match_id": "TennisExplorer match_id",
    "p1_ranking": "Rank J1", "p2_ranking": "Rank J2",
    "surface": "Suprafață Meci",
    "surface_comparison": "Comparație Suprafață",
    "p1_form_summary": "Formă J1 (V-I, meciuri disponibile pe TennisExplorer)",
    "p2_form_summary": "Formă J2 (V-I, meciuri disponibile pe TennisExplorer)",
    "implied_prob_1": "% Implicit Cotă J1",
    "implied_prob_2": "% Implicit Cotă J2",
    "composite_prob_1": "% Estimare Compusă J1 (rank+formă+rating)",
    "composite_prob_2": "% Estimare Compusă J2 (rank+formă+rating)",
    "rating_confidence": "Încredere rating carieră (0-1)",
    "p1_matches_last_3d": "Meciuri J1 în ultimele 3 zile (oboseală)",
    "p2_matches_last_3d": "Meciuri J2 în ultimele 3 zile (oboseală)",
    "fatigue_adj_pp": "Ajustare oboseală aplicată J1 (pp, + = favorizează J1)",
    "signal": "Semnal (estimare vs piață)",
    "our_min1set_p1": "% Estimare Minim 1 Set J1 (derivat)",
    "our_min1set_p2": "% Estimare Minim 1 Set J2 (derivat)",
    "our_total_sets_under": "% Estimare Sub 2.5 Seturi (derivat)",
    "our_total_sets_over": "% Estimare Peste 2.5 Seturi (derivat)",
    "p1_recent_form": "Formă recentă J1 (meciuri disponibile)",
    "p2_recent_form": "Formă recentă J2 (meciuri disponibile)",
    "h2h": "H2H",
    "odds_min1set_p1": "Cotă Minim 1 Set J1 (Da)",
    "odds_min1set_p2": "Cotă Minim 1 Set J2 (Da)",
    "odds_total_sets_line": "Linie Total Seturi",
    "odds_total_sets_under": "Cotă Sub Total Seturi",
    "odds_total_sets_over": "Cotă Peste Total Seturi",
    "odds_set1_games": "Cote Total Game-uri Set 1 (toate liniile)",
    "odds_p1_games_min_line": "Linie Minimă Disponibilă Total Game-uri J1 (meci întreg)",
    "odds_p1_games_min_line_over": "Cotă Peste la Linia Minimă J1",
    "odds_p2_games_min_line": "Linie Minimă Disponibilă Total Game-uri J2 (meci întreg)",
    "odds_p2_games_min_line_over": "Cotă Peste la Linia Minimă J2",
}


def save_report(df: pd.DataFrame, path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Tenis", index=False, header=False, startrow=1)
        ws = writer.sheets["Tenis"]

        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
        for col_idx, col_key in enumerate(df.columns, start=1):
            label = _COLUMN_LABELS.get(col_key, col_key)
            cell = ws.cell(row=1, column=col_idx, value=label)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            letter = get_column_letter(col_idx)
            ws.column_dimensions[letter].width = 28
        ws.freeze_panes = "A2"


def main() -> None:
    parser = argparse.ArgumentParser(description="Analiză meciuri tenis Superbet + stats TennisExplorer")
    parser.add_argument("--date", type=str, default=None, help="Data (YYYY-MM-DD), implicit azi")
    parser.add_argument("--output", type=str, default="output/tenis.xlsx")
    parser.add_argument("--tours", type=str, default=",".join(SUPPORTED_TOURS), help="Tur-uri, separate prin virgula (ex. atp,wta)")
    parser.add_argument("--te-delay", type=float, default=1.0, help="Pauza (secunde) intre request-uri catre TennisExplorer/Superbet")
    parser.add_argument("--extended-odds", action="store_true", help="Adauga cote minim-1-set, total seturi, total game-uri set 1 - un fetch suplimentar PER MECI, ruleaza mult mai incet")
    args = parser.parse_args()

    date = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    tours = tuple(t.strip() for t in args.tours.split(",") if t.strip())

    logger.info("Rulare pentru data %s, tur-uri %s -> %s (extended_odds=%s)", date, tours, args.output, args.extended_odds)
    df = build_report(date, tours=tours, te_delay=args.te_delay, extended_odds=args.extended_odds)
    logger.info("Total meciuri in raport: %d", len(df))

    save_report(df, args.output)
    logger.info("Salvat: %s", args.output)


if __name__ == "__main__":
    main()
