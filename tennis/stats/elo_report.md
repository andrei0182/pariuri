# Elo pe suprafata — backtest 2026-09-11 … 2026-10-10

Istoric folosit: **67916** meciuri (2026-03-26 … 2026-10-10). Ratingurile se construiesc pe tot istoricul; se evalueaza doar meciurile de la 2026-09-11, fiecare prezis inainte de update.

## Cat de bine prezice

| Varianta | Meciuri | Acuratete | Brier ↓ | Log-loss ↓ |
|---|---|---|---|---|
| Elo general (toate) | 6789 | 63.5% | 0.2228 | 0.6360 |
| Elo suprafata (toate) | 6789 | 59.0% | 0.2351 | 0.6641 |
| Elo combinat (toate) | 6789 | 62.1% | 0.2257 | 0.6423 |
| Piata — doar etalon (toate) | 6789 | 72.8% | 0.1783 | 0.5316 |
| Elo general (ambii cu ≥10 meciuri in istoric) | 5212 | 61.9% | 0.2283 | 0.6484 |
| Elo suprafata (ambii cu ≥10 meciuri in istoric) | 5212 | 57.9% | 0.2409 | 0.6772 |
| Elo combinat (ambii cu ≥10 meciuri in istoric) | 5212 | 60.5% | 0.2311 | 0.6543 |
| Piata — doar etalon (ambii cu ≥10 meciuri in istoric) | 5212 | 71.6% | 0.1853 | 0.5484 |

## Calibrare Elo combinat (ambii cu ≥10 meciuri)

| Interval | Meciuri | Elo estima | Favoritul Elo a castigat |
|---|---|---|---|
| 50-60% | 2307 | 54.9% | 52.1% |
| 60-70% | 1829 | 64.8% | 61.9% |
| 70-80% | 1126 | 74.7% | 71.5% |
| 80-90% | 494 | 83.9% | 81.2% |
| 90-100% | 66 | 92.2% | 90.9% |

## Simulare de pariere la cotele reale (ambii cu ≥10 meciuri)

Pariu de 1 unitate pe jucatorul la care Elo combinat da cu cel putin X puncte peste piata.

| Prag | Pariuri | Castigate | Cota medie | Profit | ROI |
|---|---|---|---|---|---|
| ≥5pp | 4218 | 32% | 3.80 | -784.5u | -18.6% |
| ≥10pp | 3221 | 30% | 4.00 | -630.2u | -19.6% |
| ≥15pp | 2340 | 28% | 4.21 | -487.8u | -20.8% |
| ≥20pp | 1603 | 26% | 4.40 | -351.9u | -22.0% |

## Pe suprafete (Elo combinat, toate meciurile)

| Suprafata | Meciuri | Acuratete | Brier |
|---|---|---|---|
| necunoscuta | 1640 | 67.0% | 0.2063 |
| Clay | 3894 | 65.1% | 0.2140 |
| Hard | 2936 | 60.1% | 0.2333 |
| Indoors | 501 | 59.7% | 0.2385 |

Brier: 0 = perfect, 0.25 = aruncarea monedei. Mai mic e mai bine.
