# Backtest tenis — 2026-09-08 … 2026-09-21

Meciuri testate: **568** (simplu, terminate normal, ATP/WTA/Challenger/ITF).

Scurgeri de informatie ramase: rank-ul e cel actual, iar recordul pe suprafata include si meciuri jucate dupa cel testat. Ambele favorizeaza usor modelele, nu piata.

## Comparatie (pe meciurile unde toate variantele au o estimare)

| Varianta | Meciuri | Acuratete | Brier ↓ | Log-loss ↓ |
|---|---|---|---|---|
| Doar rank | 397 | 71.5% | 0.2152 | 0.6215 |
| Model vechi (rank + forma + record general) | 397 | 68.5% | 0.2239 | 0.6394 |
| Model nou (+ suprafata, H2H, forma ponderata) | 397 | 67.5% | 0.2225 | 0.6362 |
| Piata (cote medii TennisExplorer) — doar etalon | 397 | 77.8% | 0.1633 | 0.4988 |

## Ponderi invatate din date (regresie logistica)

Antrenat pe prima jumatate a perioadei, testat pe a doua (fara sa vada rezultatele ei).

| Semnal | Pondere |
|---|---|
| rank_p | +3.221 |
| form_new_p | +0.091 |
| surface_p | +0.008 |
| h2h_p | +0.339 |
| fatigue_pp | -0.058 |

Pe jumatatea de test (284 meciuri): acuratete 68.7%, Brier 0.2060, log-loss 0.6015.
Pe aceeasi jumatate: model nou Brier 0.2199, piata Brier 0.1647 (220 meciuri cu cote).

## Calibrare model nou

Cand modelul isi favorizeaza un jucator cu X%, cat de des castiga acel jucator?

| Interval estimare | Meciuri | Estimare medie | Castigat de fapt |
|---|---|---|---|
| 50-60% | 362 | 54.6% | 60.8% |
| 60-70% | 143 | 64.1% | 76.2% |
| 70-80% | 33 | 74.2% | 78.8% |
| 80-90% | 13 | 83.0% | 92.3% |
| 90-100% | 9 | 99.0% | 88.9% |

## Pe suprafete (model nou)

| Suprafata | Meciuri | Acuratete | Brier |
|---|---|---|---|
| necunoscuta | 98 | 65.3% | 0.2329 |
| Clay | 184 | 69.6% | 0.2108 |
| Hard | 235 | 66.0% | 0.2179 |
| Indoors | 43 | 65.1% | 0.2317 |

Brier: eroarea medie la patrat a probabilitatii (0 = perfect, 0.25 = aruncarea monedei). Log-loss: pedepseste mai tare increderea mare gresita. La ambele, mai mic e mai bine.
