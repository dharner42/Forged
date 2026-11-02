# Model results

Generated 2026-10-31 01:48 UTC by `python -m models.train`. These numbers are copied into the README. If you retrain, this file is the source of truth.

## 24-hour failure risk (the model the dashboard runs)

Question: at this machine-hour, does a component failure happen in the next 24 hours?

- Fit on January–July 2015. August is used only to calibrate probabilities (isotonic regression) and to pick the decision threshold. September 1 through December 30 at 06:00 is the test period.
- Class imbalance is large. Prevalence on the test rows is 1.8%. A classifier that never predicts a failure would be about 98.2% accurate and would have an F1 of 0.
- `scale_pos_weight` is used while fitting so the trees see the rare failures. The probability the dashboard multiplies into the priority formula is the calibrated one.

| Model | Precision | Recall | F1 | PR-AUC | Threshold |
| --- | ---: | ---: | ---: | ---: | ---: |
| Logistic regression (baseline) | 0.799 | 0.845 | 0.821 | 0.836 | 0.492 |
| XGBoost | 0.994 | 0.992 | 0.993 | 0.988 | 1.000 |

XGBoost confusion matrix on the test hours: 5274 true positives, 33 false positives, 40 false negatives, 283353 true negatives.

The mean calibrated probability on those hours is 0.018, next to a failure rate of 0.018. In aggregate the probabilities match the base rate. Machine by machine they pile up near 0 and near 1 (test median 0.000, 99th percentile 1.000), because this simulator leaves a loud fingerprint and isotonic calibration then pushes scores to the ends. Do not quote the 0.99 as what a real plant will get. The logistic regression is the floor that transfers: it is already strong, and the trees pick up the rest of a nearly rule-shaped failure process.

PR-AUC on the uncalibrated scores is 0.998 for XGBoost and 0.857 for logistic regression. Calibration is monotone, so ranking quality barely moves. The table above is the calibrated score the product uses.

Red band: calibrated probability at or above 1.000 (the August threshold that maximized F1). Amber: at or above 0.500 and below red. Green: below amber. Test-set probability quantiles: median 0.000, 90th 0.000, 95th 0.000, 99th 1.000.

When a failure is coming, a second model guesses the component. Macro F1 on test hours that do fail within 24 hours: 1.000 (5314 rows). On this file that score is essentially perfect, which means the simulator's component rule is recoverable from the same features. Treat it as a property of the dataset. The guess still only picks which simulated part to check.

## Remaining useful life (C-MAPSS FD001)

100 training engines, 20631 cycles. Labels are remaining cycles, capped at 125. Constant columns dropped before modeling: op3, s1, s5, s10, s16, s18, s19.

An engine is never in both sides of a split. Random forest and XGBoost are tuned with GroupKFold (3 folds) on the training engines. The winner is the better cross-validated model, not the better test score. The official test file is scored once.

| Model | Features | CV RMSE | RMSE vs official RUL | RMSE vs RUL capped at 125 |
| --- | --- | ---: | ---: | ---: |
| Linear regression | raw sensors | — | 21.90 | 20.59 |
| Linear regression | raw + rolling 5/10 | — | 21.56 | 20.51 |
| Random forest | raw + rolling 5/10 | 18.82 | 20.13 | 19.23 |
| XGBoost | raw + rolling 5/10 | 18.64 | 19.47 | 18.55 |

Saved model: **xgboost** with parameters `{'max_depth': 3, 'n_estimators': 150}`. Its official-file RMSE is 19.47 cycles. RMSE against remaining life capped at 125 is 18.55 cycles. The second number matches the training target. The first number is what `RUL_FD001.txt` actually contains, including engines with more than 125 cycles left.

Error is larger when the official remaining life is still long (23.4 RMSE beyond 125 cycles versus 17.1 when fewer than 30 cycles remain). Training labels were capped at 125, so the model is not allowed to predict a long healthy life, and engines that fail much later pile up near that cap. It is most useful close to failure, which is also when a maintenance lead would act.

## AI4I 2020 failure type

10,000 synthetic milling-process rows. 3.4% have any machine failure, so a model that always says "no failure" is 96.6% accurate. The split is stratified 75/25, seed 42. Features: type (L is the reference), air temperature, process temperature, rpm, torque, tool wear, power (torque × rpm), and temperature difference.

| Failure mode | Test positives | Logistic F1 | XGBoost F1 |
| --- | ---: | ---: | ---: |
| Any failure | 85 | 0.279 | 0.608 |
| TWF | 11 | 0.086 | 0.074 |
| HDF | 29 | 0.500 | 0.931 |
| PWF | 24 | 0.495 | 0.941 |
| OSF | 24 | 0.585 | 0.885 |

RNF has 19 rows. The dataset defines it as a random failure with no causal signal, so it is stored and not used as a target. Mode counts in the full file: TWF 46, HDF 115, PWF 95, OSF 98.

## Does the morning list beat "fix the old machines"?

On 115 mornings from September through late December, the priority formula's top 10 had an average of 2.49 machines that failed within 7 days, versus 1.50 for oldest-machine-first, 2.49 for failure probability alone, and 1.25 for a random 10 machines.

The ranking in that sentence is the published formula, priority = probability × impact × parts factor. It does not use the 24-hour "just serviced" queue adjustment. Parts and impact are simulated, so this is a test of the weighting scheme on the synthetic plant, not of a real storeroom.

## What the priority list is worth, in the planning rates

Assumptions live in `cost_assumptions.py` and nowhere else. Downtime is priced by production impact. A missed failure costs unplanned downtime, emergency labor, and the part. A failure caught on the list costs a shorter planned stop, straight-time labor, and the same part, with the expedite multiplier when that component is out of stock or below its reorder point. A list slot spent on a machine that does not fail costs a short inspection. The backtest list length is fixed, so the strategies are compared on the same number of jobs.

This edition prices the published hit-rate gap on one reference machine: impact 3, comp2, part in stock. One extra catch on that machine is $4,838.

| Comparison | Extra catches per morning | USD per morning | USD over the window |
| --- | ---: | ---: | ---: |
| Versus oldest-machine-first | 0.98 | $4,753 | $546,638 |
| Versus a random 10 | 1.23 | $5,961 | $685,474 |

Over 115 mornings, the rates in cost_assumptions.py applied to one reference machine (impact 3, comp2, part in stock) price the priority list at $546,638 versus oldest-machine-first and $685,474 versus a random 10. One extra catch on that machine is $4,838: the unplanned stop, plus the inspection the list slot no longer wastes, minus the planned repair. The stored backtest keeps average hits, not the machine ids, so this edition does not use each machine's own impact. Impact, stock, and these rates are assumptions, not a supplier's invoices. `make train` replaces this with the sum over the actual machines on each morning.

Demo plant clock: 2015-11-23 06:00:00. That morning is the November Monday whose priority scores are most spread out, and at least one machine is out of the green band when such a Monday exists. It was not chosen by looking at which machine failed later.
