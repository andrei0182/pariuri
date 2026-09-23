# Elo pe suprafata — backtest 2026-08-23 … 2026-09-21

Istoric folosit: **62101** meciuri (2026-03-26 … 2026-09-21). Ratingurile se construiesc pe tot istoricul; se evalueaza doar meciurile de la 2026-08-23, fiecare prezis inainte de update.

## Cat de bine prezice

| Varianta | Meciuri | Acuratete | Brier ↓ | Log-loss ↓ |
|---|---|---|---|---|
| Elo general (toate) | 7377 | 61.9% | 0.2288 | 0.6499 |
| Elo suprafata (toate) | 7377 | 58.7% | 0.2400 | 0.6745 |
| Elo combinat (toate) | 7377 | 61.5% | 0.2309 | 0.6537 |
| Piata — doar etalon (toate) | 7377 | 72.9% | 0.1778 | 0.5305 |
| Elo general (ambii cu ≥10 meciuri in istoric) | 5256 | 60.5% | 0.2347 | 0.6633 |
| Elo suprafata (ambii cu ≥10 meciuri in istoric) | 5256 | 57.5% | 0.2461 | 0.6888 |
| Elo combinat (ambii cu ≥10 meciuri in istoric) | 5256 | 60.0% | 0.2366 | 0.6665 |
| Piata — doar etalon (ambii cu ≥10 meciuri in istoric) | 5256 | 71.8% | 0.1853 | 0.5490 |

## Calibrare Elo combinat (ambii cu ≥10 meciuri)

| Interval | Meciuri | Elo estima | Favoritul Elo a castigat |
|---|---|---|---|
| 50-60% | 2331 | 54.9% | 54.0% |
| 60-70% | 1864 | 64.8% | 59.2% |
| 70-80% | 1144 | 74.5% | 71.4% |
| 80-90% | 427 | 83.9% | 75.9% |
| 90-100% | 62 | 92.0% | 91.9% |

## Simulare de pariere la cotele reale (ambii cu ≥10 meciuri)

Pariu de 1 unitate pe jucatorul la care Elo combinat da cu cel putin X puncte peste piata.

| Prag | Pariuri | Castigate | Cota medie | Profit | ROI |
|---|---|---|---|---|---|
| ≥5pp | 4256 | 31% | 3.88 | -816.2u | -19.2% |
| ≥10pp | 3330 | 29% | 4.09 | -680.4u | -20.4% |
| ≥15pp | 2490 | 27% | 4.36 | -529.1u | -21.2% |
| ≥20pp | 1788 | 25% | 4.58 | -380.3u | -21.3% |

## Pe suprafete (Elo combinat, toate meciurile)

| Suprafata | Meciuri | Acuratete | Brier |
|---|---|---|---|
| necunoscuta | 1790 | 64.7% | 0.2152 |
| Clay | 4390 | 62.3% | 0.2247 |
| Hard | 4105 | 60.0% | 0.2364 |
| Indoors | 167 | 53.3% | 0.2569 |

Brier: 0 = perfect, 0.25 = aruncarea monedei. Mai mic e mai bine.
