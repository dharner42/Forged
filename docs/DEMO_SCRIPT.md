# Demo script

Three minutes. Record it yourself. This file is the script, not a claim that a video already exists.

The plant clock should be on the November demo morning (`results/metrics.json` records the timestamp). Do not move it before you start. Lines, impact, parts, and technician names are simulated. Say that out loud once.

## 0:00 The problem

A maintenance lead at a 20 to 500 person plant, including a defense supplier, starts the shift with more machines than people. The question is not "is predictive maintenance possible." It is "what do we fix first today, and do we have the part."

## 0:20 Fleet readiness

Open the Fleet page. Read the green / amber / red counts and the readiness percentage. Point at the morning trend and say it only shows days at or before the plant clock. The model never trained on September through December. Those months are the test.

## 0:50 Why the top machine is first

Open the first row. On the machine page, read the reason in plain language: a hot sensor, how long since that component was replaced, and whether the simulated part is short. Then show the contribution bars. Those are the model's own feature contributions, not a second opinion from a language model.

Say the formula once: probability times production impact times a parts factor of 1.5 when the part is out of stock or below its reorder point.

## 1:30 Create the work order, then close it

Create a work order. A simulated technician is assigned by skill and by who already has the fewest open jobs. Go back to the queue, mark it repaired, and refresh. The machine drops. Two things happened: the replacement age went to zero, and a shop rule multiplies the queue score by 0.15 for 24 hours so a hot sensor trace does not send a second technician to a machine you just finished. The probability is still on the page. The backtest of the formula does not use that 24-hour rule.

## 2:00 Parts

Open Parts and technicians. Say, clearly, that every stock number and every name on this page is simulated. The public datasets do not have a storeroom. The alert is: predicted demand from the amber and red machines exceeds what is on the shelf, and the lead time is longer than the 24-hour horizon, so the part will not arrive in time.

## 2:20 What was modeled

Three models, none of them a language model.

- Azure sample: will this machine fail in 24 hours. Time split. Precision, recall, F1, and PR-AUC against a logistic regression. Read the numbers from `results/results.md`.
- NASA C-MAPSS FD001: remaining cycles. Engines are not split across train and test. RMSE against the official file.
- AI4I: failure versus no failure, scored by F1 because only about 3 percent of rows fail. Accuracy would look excellent for a model that never raises an alarm.

## 2:45 What is next

The ontology is real and small: machines, readings, faults, failures, maintenance, parts, technicians, work orders, scores. Swapping in a shop means mapping their historian and their CMMS onto those tables and refitting the 24-hour model on their failures. The simulated stock and the simulated roster are the first things a real plant would replace. Discovery calls with maintenance managers are still to be done. The score weights are a starting point, not a finding from those calls.
