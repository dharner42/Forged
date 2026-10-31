# Demo script

Three minutes. Record it yourself. This file is the script, not a claim that a video already exists.

The plant clock should be on the November demo morning (`results/metrics.json` records the timestamp). Do not move it before you start. Lines, impact, parts, and technician names are simulated. Say that out loud once.

## 0:00 The problem

A maintenance lead at a 20 to 500 person plant, including a defense supplier, starts the shift with more machines than people. The question is not "is predictive maintenance possible." It is "what do we fix first today, and do we have the part."

## 0:20 Fleet readiness

Open the Fleet page. Read the green / amber / red counts. Then read "This shift." Machine 19 is the highest priority and it is on the do-not-start list: comp4 is out of stock, and the only general technician is on swing, not on this day shift. Machines 61 and 77 are the ones this crew can start. Say that the roster and the stock are simulated, and that this plan does not change the score the backtest uses.

## 0:50 Why machine 19 ranks first anyway

Open machine 19. Read the reason: vibration, a recent error, component age, and the missing part. Show the contribution bars. Those come from the tree model. Say the formula once: probability times production impact times 1.5 when the part is out of stock or below its reorder point. Then say the calibrated score on this file sits near 0% or 100%, so you still read the sensor reason before you dispatch.

## 1:30 Create the work order on a job you can start

Create a work order on machine 61, not 19. E. Shah is on the day shift and has the hydraulics skill. Mark it repaired. The machine drops. The replacement is logged at the plant clock, and a shop rule multiplies the queue score by 0.15 for 24 hours. The probability is still on the page. The backtest of the formula does not use that rule, and it does not use the shift plan.

## 2:00 Parts

Open Parts and technicians. Say, clearly, that every stock number and every name on this page is simulated. The public datasets do not have a storeroom. The alert is: predicted demand from the amber and red machines exceeds what is on the shelf, and the lead time is longer than the 24-hour horizon, so the part will not arrive in time.

## 2:20 What was modeled

Three models, none of them a language model.

- Azure sample: will this machine fail in 24 hours. Time split. Precision, recall, F1, and PR-AUC against a logistic regression. Read the numbers from `results/results.md`.
- NASA C-MAPSS FD001: remaining cycles. Engines are not split across train and test. RMSE against the official file.
- AI4I: failure versus no failure, scored by F1 because only about 3 percent of rows fail. Accuracy would look excellent for a model that never raises an alarm.

## 2:45 What is next

The ontology is real and small: machines, readings, faults, failures, maintenance, parts, technicians, work orders, scores. Swapping in a shop means mapping their historian and their CMMS onto those tables and refitting the 24-hour model on their failures. The simulated stock and the simulated roster are the first things a real plant would replace. Discovery calls with maintenance managers are still to be done. The score weights are a starting point, not a finding from those calls.
