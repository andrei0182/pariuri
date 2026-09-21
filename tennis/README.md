# Tenis — analiză meciuri Superbet + istoric/formă jucători

**Status: Phase 0 — scaffold de reconnaissance, copiat din structura care a
funcționat la [[bet]] și [[SuperBet]], nu un scraper funcțional încă.**

## Scop

Pentru meciurile de tenis disponibile pe Superbet.ro, combină:
1. **Cotele Superbet** (1X2 / minim 1 set / total game-uri) pentru meciurile
   zilei
2. **Statistici jucători** de pe Tennis Explorer (H2H, formă recentă, record
   pe suprafață) — plus orice semnal de accidentare/retragere disponibil

...într-un raport Excel zilnic care arată șansa estimată vs. cota oferită.

## De ce pornim tot ca scaffold, nu cod gata făcut

Exact lecția de la SuperBet: presupunerile greșite despre structura datelor
(JSON API vs. randare JS vs. HTML server-side) au consumat timp real la
`bet` și `SuperBet`. Aici avem DOUĂ surse necunoscute, nu una:

- **Superbet.ro — tenis**: structura URL e CONFIRMATĂ (vezi mai jos), dar
  endpoint-ul JSON de events găsit la fotbal (`sports=5`) — sport id-ul
  pentru tenis NU e confirmat, și numele market-ului pentru "meci câștigat"
  (nu există egalitate la tenis, deci nu va fi "Final" cu 1/X/2 — probabil
  doar 1/2, dar numele exact al market-ului trebuie verificat cu
  `tools/inspect_page.py` sau curl, ca la fotbal).
- **TennisExplorer.com**: NU știm încă dacă folosește același tipar AJAX cu
  token `ts=` ca BetExplorer (sunt site-uri surori, dar tenisul are pagini
  de jucător, nu pagini de echipă/clasament — structura poate diferi mult).
  Trebuie investigat separat, cu `tools/inspect_page.py`.

**Nu presupune, investighează întâi.**

## Confirmat (2026-09-15, prin browsing manual)

- Superbet.ro grupează tenisul sub `/pariuri-sportive/tenis/{tur}/{slug-turneu}/toate`,
  unde `{tur}` e unul din: `atp`, `wta`, `wta-125`, `challenger` (posibil și
  `itf`, `esport-tenis` separat, `tenis-de-masa` separat — tenis de masă NU
  e același sport).
  Exemple văzute: `tenis/atp/atp-us-open`, `tenis/wta/roland-garros-2025`,
  `tenis/challenger/biella-ita`, `tenis/wta-125/valencia-spa`.
  Asta diferă de fotbal, unde slug-ul e `fotbal---{țară}---{ligă}` — la
  tenis pare să fie `tenis---{tur}---{turneu}` (de confirmat exact în
  `sportTournamentMap_ro-RO.json`, care conține și intrările de tenis, nu
  doar fotbal — `tournaments.py` de la SuperBet doar filtra pe `fotbal---`).
- Cotele afișate pe pagină includ: rezultat final (1/2, fără egalitate),
  minim 1 set, total game-uri, handicap game-uri, scor corect.
- Perechi de dublu apar separat (ex. "Challenger - Biella (ITA) - Dublu") —
  de exclus sau tratat separat față de simplu.

## NEconfirmat — de investigat primul (Phase 0)

1. Sport id-ul pentru tenis în endpoint-ul `v3/ro-RO/events` (la fotbal e
   `sports=5`).
2. Numele exact al market-ului de "rezultat final" pentru tenis (probabil
   NU se numește "Final" cu odds 1/X/2 ca la fotbal, ci ceva cu doar 1/2).
3. Dacă TennisExplorer.com răspunde deja la `requests` simplu, sau are
   nevoie de Selenium / are un tipar AJAX diferit.
4. Cum arată o pagină de jucător pe TennisExplorer (H2H, formă, record pe
   suprafață) — structura HTML/selectori.
5. Dacă există un semnal fiabil de accidentare/retragere (WD/RET) — cel mai
   probabil doar dispariția jucătorului din lista Superbet, nu un feed
   dedicat.

## Setup

```bash
pip install -r requirements.txt
```

## Pasul 1 — investighează (fă asta primul)

```bash
python tools/inspect_page.py "https://superbet.ro/pariuri-sportive/tenis/atp/atp-us-open/toate"
python tools/inspect_page.py "https://www.tennisexplorer.com/player/<nume-jucator>/"
```

Verifică și manual, în DevTools → Network → Fetch/XHR, pe o pagină de tenis
Superbet și pe o pagină de jucător TennisExplorer, exact cum s-a făcut la
celelalte două proiecte.

## Structura proiectului

- `tenis_scraper/driver.py` — headless Chrome, copiat identic din
  SuperBet (folosește-l doar dacă investigarea arată că e nevoie de JS).
- `tenis_scraper/models.py` — model de date pentru meci de tenis (jucători,
  nu echipe; fără egalitate; seturi/game-uri, nu goluri).
- `tenis_scraper/tournaments.py` — adaptat din SuperBet pentru slug-urile
  `tenis---{tur}---{turneu}` — NEconfirmat, de verificat cu JSON-ul real.
- `tenis_scraper/events.py` — copiat din tiparul SuperBet (JSON API), cu
  `TENNIS_SPORT_ID` marcat UNCONFIRMED și `parse_event` marcat de rescris
  pentru forma reală a market-ului de tenis.
- `tenis_scraper/tennisexplorer.py` — modul NOU, scaffold gol pentru
  H2H/formă/suprafață — nimic confirmat încă, doar structura de funcții.
- `tenis_scraper/export.py` — adaptat din SuperBet, coloane pentru tenis.
- `tools/inspect_page.py` — copiat identic, generic pentru orice URL.
- `output/` — unde vor merge fișierele Excel exportate (gitignored).

## Odată ce datele sunt confirmate

Actualizează acest README și `tenis_scraper/models.py` cu structura reală,
apoi construiește logica de extragere — exact fluxul care a funcționat la
celelalte două proiecte.
