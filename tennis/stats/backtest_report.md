# Backtest tenis — 2026-09-16 … 2026-09-29

Meciuri testate: **578** (simplu, terminate normal, ATP/WTA/Challenger/ITF).

Scurgeri de informatie ramase: rank-ul e cel actual, iar recordul pe suprafata include si meciuri jucate dupa cel testat. Ambele favorizeaza usor modelele, nu piata.

## Comparatie (pe meciurile unde toate variantele au o estimare)

| Varianta | Meciuri | Acuratete | Brier ↓ | Log-loss ↓ |
|---|---|---|---|---|
| Doar rank | 374 | 70.1% | 0.2158 | 0.6224 |
| Model vechi (rank + forma + record general) | 374 | 67.6% | 0.2247 | 0.6407 |
| Model nou (+ suprafata, H2H, forma ponderata) | 374 | 65.2% | 0.2247 | 0.6404 |
| Piata (cote medii TennisExplorer) — doar etalon | 374 | 74.6% | 0.1666 | 0.5020 |

## Ponderi invatate din date (regresie logistica)

Antrenat pe prima jumatate a perioadei, testat pe a doua (fara sa vada rezultatele ei).

| Semnal | Pondere |
|---|---|
| rank_p | +3.258 |
| form_new_p | +0.130 |
| surface_p | -0.023 |
| h2h_p | +0.428 |
| fatigue_pp | +0.140 |

Pe jumatatea de test (289 meciuri): acuratete 67.1%, Brier 0.2145, log-loss 0.6151.
Pe aceeasi jumatate: model nou Brier 0.2248, piata Brier 0.1747 (198 meciuri cu cote).

## Calibrare model nou

Cand modelul isi favorizeaza un jucator cu X%, cat de des castiga acel jucator?

| Interval estimare | Meciuri | Estimare medie | Castigat de fapt |
|---|---|---|---|
| 50-60% | 372 | 54.4% | 60.5% |
| 60-70% | 119 | 64.1% | 72.3% |
| 70-80% | 34 | 75.1% | 82.4% |
| 80-90% | 18 | 83.5% | 88.9% |
| 90-100% | 22 | 98.7% | 72.7% |

## Pe suprafete (model nou)

| Suprafata | Meciuri | Acuratete | Brier |
|---|---|---|---|
| necunoscuta | 95 | 70.5% | 0.2024 |
| Clay | 161 | 60.9% | 0.2298 |
| Hard | 270 | 67.8% | 0.2256 |
| Indoors | 39 | 59.0% | 0.2404 |

Brier: eroarea medie la patrat a probabilitatii (0 = perfect, 0.25 = aruncarea monedei). Log-loss: pedepseste mai tare increderea mare gresita. La ambele, mai mic e mai bine.
