# Elo pe suprafata — backtest 2026-09-10 … 2026-10-09

Istoric folosit: **67784** meciuri (2026-03-26 … 2026-10-09). Ratingurile se construiesc pe tot istoricul; se evalueaza doar meciurile de la 2026-09-10, fiecare prezis inainte de update.

## Cat de bine prezice

| Varianta | Meciuri | Acuratete | Brier ↓ | Log-loss ↓ |
|---|---|---|---|---|
| Elo general (toate) | 6915 | 63.4% | 0.2232 | 0.6369 |
| Elo suprafata (toate) | 6915 | 59.0% | 0.2354 | 0.6646 |
| Elo combinat (toate) | 6915 | 61.9% | 0.2261 | 0.6429 |
| Piata — doar etalon (toate) | 6915 | 73.1% | 0.1777 | 0.5302 |
| Elo general (ambii cu ≥10 meciuri in istoric) | 5296 | 61.8% | 0.2287 | 0.6492 |
| Elo suprafata (ambii cu ≥10 meciuri in istoric) | 5296 | 57.8% | 0.2412 | 0.6777 |
| Elo combinat (ambii cu ≥10 meciuri in istoric) | 5296 | 60.3% | 0.2314 | 0.6549 |
| Piata — doar etalon (ambii cu ≥10 meciuri in istoric) | 5296 | 71.8% | 0.1847 | 0.5472 |

## Calibrare Elo combinat (ambii cu ≥10 meciuri)

| Interval | Meciuri | Elo estima | Favoritul Elo a castigat |
|---|---|---|---|
| 50-60% | 2346 | 54.8% | 51.8% |
| 60-70% | 1860 | 64.8% | 61.8% |
| 70-80% | 1145 | 74.7% | 71.5% |
| 80-90% | 495 | 83.9% | 81.0% |
| 90-100% | 66 | 92.2% | 90.9% |

## Simulare de pariere la cotele reale (ambii cu ≥10 meciuri)

Pariu de 1 unitate pe jucatorul la care Elo combinat da cu cel putin X puncte peste piata.

| Prag | Pariuri | Castigate | Cota medie | Profit | ROI |
|---|---|---|---|---|---|
| ≥5pp | 4283 | 32% | 3.81 | -815.7u | -19.0% |
| ≥10pp | 3280 | 30% | 4.02 | -663.7u | -20.2% |
| ≥15pp | 2394 | 27% | 4.23 | -525.1u | -21.9% |
| ≥20pp | 1651 | 25% | 4.42 | -379.8u | -23.0% |

## Pe suprafete (Elo combinat, toate meciurile)

| Suprafata | Meciuri | Acuratete | Brier |
|---|---|---|---|
| necunoscuta | 1632 | 67.0% | 0.2060 |
| Clay | 3912 | 65.0% | 0.2141 |
| Hard | 3049 | 60.0% | 0.2335 |
| Indoors | 499 | 59.5% | 0.2385 |

Brier: 0 = perfect, 0.25 = aruncarea monedei. Mai mic e mai bine.
