# Backtest tenis — 2026-09-14 … 2026-09-27

Meciuri testate: **578** (simplu, terminate normal, ATP/WTA/Challenger/ITF).

Scurgeri de informatie ramase: rank-ul e cel actual, iar recordul pe suprafata include si meciuri jucate dupa cel testat. Ambele favorizeaza usor modelele, nu piata.

## Comparatie (pe meciurile unde toate variantele au o estimare)

| Varianta | Meciuri | Acuratete | Brier ↓ | Log-loss ↓ |
|---|---|---|---|---|
| Doar rank | 387 | 69.3% | 0.2181 | 0.6273 |
| Model vechi (rank + forma + record general) | 387 | 65.9% | 0.2267 | 0.6458 |
| Model nou (+ suprafata, H2H, forma ponderata) | 387 | 66.1% | 0.2274 | 0.6473 |
| Piata (cote medii TennisExplorer) — doar etalon | 387 | 73.1% | 0.1775 | 0.5312 |

## Ponderi invatate din date (regresie logistica)

Antrenat pe prima jumatate a perioadei, testat pe a doua (fara sa vada rezultatele ei).

| Semnal | Pondere |
|---|---|
| rank_p | +3.055 |
| form_new_p | +0.053 |
| surface_p | +0.061 |
| h2h_p | +0.287 |
| fatigue_pp | +0.164 |

Pe jumatatea de test (289 meciuri): acuratete 66.4%, Brier 0.2220, log-loss 0.6350.
Pe aceeasi jumatate: model nou Brier 0.2435, piata Brier 0.1944 (229 meciuri cu cote).

## Calibrare model nou

Cand modelul isi favorizeaza un jucator cu X%, cat de des castiga acel jucator?

| Interval estimare | Meciuri | Estimare medie | Castigat de fapt |
|---|---|---|---|
| 50-60% | 363 | 54.2% | 62.0% |
| 60-70% | 137 | 64.0% | 74.5% |
| 70-80% | 41 | 74.6% | 78.0% |
| 80-90% | 7 | 84.4% | 85.7% |
| 90-100% | 16 | 99.2% | 50.0% |

## Pe suprafete (model nou)

| Suprafata | Meciuri | Acuratete | Brier |
|---|---|---|---|
| necunoscuta | 98 | 69.4% | 0.2124 |
| Clay | 155 | 67.7% | 0.2288 |
| Hard | 263 | 66.9% | 0.2366 |
| Indoors | 48 | 50.0% | 0.2458 |

Brier: eroarea medie la patrat a probabilitatii (0 = perfect, 0.25 = aruncarea monedei). Log-loss: pedepseste mai tare increderea mare gresita. La ambele, mai mic e mai bine.
