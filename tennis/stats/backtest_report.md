# Backtest tenis — 2026-09-22 … 2026-10-05

Meciuri testate: **573** (simplu, terminate normal, ATP/WTA/Challenger/ITF).

Scurgeri de informatie ramase: rank-ul e cel actual, iar recordul pe suprafata include si meciuri jucate dupa cel testat. Ambele favorizeaza usor modelele, nu piata.

## Comparatie (pe meciurile unde toate variantele au o estimare)

| Varianta | Meciuri | Acuratete | Brier ↓ | Log-loss ↓ |
|---|---|---|---|---|
| Doar rank | 374 | 69.3% | 0.2154 | 0.6218 |
| Model vechi (rank + forma + record general) | 374 | 60.7% | 0.2296 | 0.6505 |
| Model nou (+ suprafata, H2H, forma ponderata) | 374 | 57.5% | 0.2329 | 0.6567 |
| Piata (cote medii TennisExplorer) — doar etalon | 374 | 73.3% | 0.1835 | 0.5441 |

## Ponderi invatate din date (regresie logistica)

Antrenat pe prima jumatate a perioadei, testat pe a doua (fara sa vada rezultatele ei).

| Semnal | Pondere |
|---|---|
| rank_p | +2.288 |
| form_new_p | +0.099 |
| surface_p | +0.095 |
| h2h_p | -0.366 |
| fatigue_pp | +0.263 |

Pe jumatatea de test (287 meciuri): acuratete 65.9%, Brier 0.2068, log-loss 0.5994.
Pe aceeasi jumatate: model nou Brier 0.2236, piata Brier 0.1745 (204 meciuri cu cote).

## Calibrare model nou

Cand modelul isi favorizeaza un jucator cu X%, cat de des castiga acel jucator?

| Interval estimare | Meciuri | Estimare medie | Castigat de fapt |
|---|---|---|---|
| 50-60% | 359 | 54.3% | 54.3% |
| 60-70% | 122 | 63.7% | 69.7% |
| 70-80% | 37 | 74.3% | 83.8% |
| 80-90% | 18 | 84.3% | 83.3% |
| 90-100% | 22 | 98.8% | 77.3% |

## Pe suprafete (model nou)

| Suprafata | Meciuri | Acuratete | Brier |
|---|---|---|---|
| necunoscuta | 65 | 70.8% | 0.2055 |
| Clay | 130 | 59.2% | 0.2255 |
| Hard | 311 | 60.5% | 0.2348 |
| Indoors | 52 | 61.5% | 0.2182 |

Brier: eroarea medie la patrat a probabilitatii (0 = perfect, 0.25 = aruncarea monedei). Log-loss: pedepseste mai tare increderea mare gresita. La ambele, mai mic e mai bine.
