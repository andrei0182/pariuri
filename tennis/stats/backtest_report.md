# Backtest tenis — 2026-09-28 … 2026-10-11

Meciuri testate: **578** (simplu, terminate normal, ATP/WTA/Challenger/ITF).

Scurgeri de informatie ramase: rank-ul e cel actual, iar recordul pe suprafata include si meciuri jucate dupa cel testat. Ambele favorizeaza usor modelele, nu piata.

## Comparatie (pe meciurile unde toate variantele au o estimare)

| Varianta | Meciuri | Acuratete | Brier ↓ | Log-loss ↓ |
|---|---|---|---|---|
| Doar rank | 396 | 69.4% | 0.2202 | 0.6321 |
| Model vechi (rank + forma + record general) | 396 | 64.6% | 0.2298 | 0.6514 |
| Model nou (+ suprafata, H2H, forma ponderata) | 396 | 64.6% | 0.2298 | 0.6514 |
| Piata (cote medii TennisExplorer) — doar etalon | 396 | 71.5% | 0.1837 | 0.5434 |

## Ponderi invatate din date (regresie logistica)

Antrenat pe prima jumatate a perioadei, testat pe a doua (fara sa vada rezultatele ei).

| Semnal | Pondere |
|---|---|
| rank_p | +2.042 |
| form_new_p | +0.069 |
| surface_p | +0.134 |
| h2h_p | +0.375 |
| fatigue_pp | -0.055 |

Pe jumatatea de test (289 meciuri): acuratete 67.8%, Brier 0.2073, log-loss 0.6007.
Pe aceeasi jumatate: model nou Brier 0.2264, piata Brier 0.1871 (216 meciuri cu cote).

## Calibrare model nou

Cand modelul isi favorizeaza un jucator cu X%, cat de des castiga acel jucator?

| Interval estimare | Meciuri | Estimare medie | Castigat de fapt |
|---|---|---|---|
| 50-60% | 350 | 54.3% | 63.4% |
| 60-70% | 139 | 63.8% | 68.3% |
| 70-80% | 38 | 74.8% | 81.6% |
| 80-90% | 22 | 83.9% | 81.8% |
| 90-100% | 16 | 99.5% | 81.2% |

## Pe suprafete (model nou)

| Suprafata | Meciuri | Acuratete | Brier |
|---|---|---|---|
| necunoscuta | 69 | 66.7% | 0.2147 |
| Clay | 159 | 68.6% | 0.2133 |
| Hard | 278 | 65.8% | 0.2333 |
| Indoors | 59 | 69.5% | 0.2057 |

Brier: eroarea medie la patrat a probabilitatii (0 = perfect, 0.25 = aruncarea monedei). Log-loss: pedepseste mai tare increderea mare gresita. La ambele, mai mic e mai bine.
