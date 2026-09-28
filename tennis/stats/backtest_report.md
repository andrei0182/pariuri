# Backtest tenis — 2026-09-13 … 2026-09-26

Meciuri testate: **566** (simplu, terminate normal, ATP/WTA/Challenger/ITF).

Scurgeri de informatie ramase: rank-ul e cel actual, iar recordul pe suprafata include si meciuri jucate dupa cel testat. Ambele favorizeaza usor modelele, nu piata.

## Comparatie (pe meciurile unde toate variantele au o estimare)

| Varianta | Meciuri | Acuratete | Brier ↓ | Log-loss ↓ |
|---|---|---|---|---|
| Doar rank | 375 | 67.2% | 0.2203 | 0.6319 |
| Model vechi (rank + forma + record general) | 375 | 64.5% | 0.2274 | 0.6473 |
| Model nou (+ suprafata, H2H, forma ponderata) | 375 | 63.5% | 0.2252 | 0.6426 |
| Piata (cote medii TennisExplorer) — doar etalon | 375 | 73.6% | 0.1785 | 0.5329 |

## Ponderi invatate din date (regresie logistica)

Antrenat pe prima jumatate a perioadei, testat pe a doua (fara sa vada rezultatele ei).

| Semnal | Pondere |
|---|---|
| rank_p | +2.537 |
| form_new_p | +0.055 |
| surface_p | +0.131 |
| h2h_p | +1.032 |
| fatigue_pp | -0.067 |

Pe jumatatea de test (283 meciuri): acuratete 63.6%, Brier 0.2286, log-loss 0.6569.
Pe aceeasi jumatate: model nou Brier 0.2320, piata Brier 0.1959 (225 meciuri cu cote).

## Calibrare model nou

Cand modelul isi favorizeaza un jucator cu X%, cat de des castiga acel jucator?

| Interval estimare | Meciuri | Estimare medie | Castigat de fapt |
|---|---|---|---|
| 50-60% | 347 | 54.7% | 58.5% |
| 60-70% | 130 | 64.1% | 76.2% |
| 70-80% | 36 | 73.6% | 66.7% |
| 80-90% | 21 | 83.0% | 66.7% |
| 90-100% | 22 | 99.0% | 72.7% |

## Pe suprafete (model nou)

| Suprafata | Meciuri | Acuratete | Brier |
|---|---|---|---|
| necunoscuta | 90 | 64.4% | 0.2365 |
| Clay | 184 | 69.0% | 0.2205 |
| Hard | 229 | 60.7% | 0.2263 |
| Indoors | 53 | 58.5% | 0.2541 |

Brier: eroarea medie la patrat a probabilitatii (0 = perfect, 0.25 = aruncarea monedei). Log-loss: pedepseste mai tare increderea mare gresita. La ambele, mai mic e mai bine.
