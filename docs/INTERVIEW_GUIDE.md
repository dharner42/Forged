# How to defend Forged Machine Monitoring

This is the plain-language version of the design. Read it out loud once. The numbers below are from the training run recorded in `results/results.md`. If you retrain, read that file again and update the three numbers you memorize: the 24-hour F1, the remaining-life RMSE, and the AI4I F1.

You do not need to pretend you wrote every line. You do need to be able to open a file and say what it is for.

## The one-minute version

A maintenance lead at a 20 to 500 person plant starts the shift with more machines than people. Forged Machine Monitoring ranks what to fix first. It uses a real failure model on a public machine dataset, then multiplies that risk by how much production the machine stops and by whether the part is on the shelf.

Three models, no language model:

- Will this machine fail in the next 24 hours? That is the number on the screen.
- How many cycles does a turbine engine have left? That is a separate skill check on NASA data.
- Can you tell a rare failure from a normal row? That is a skill check on the AI4I set, scored with F1 because accuracy would lie.

Parts, technician names, production lines, and the 1-to-5 impact scores are simulated. Say that before anyone asks.

## Numbers worth memorizing

**24-hour failure model, Azure sample, September–December 2015.** About 1.8% of machine-hours are failures. A model that never raises an alarm is 98.2% accurate and has an F1 of zero.

| | Precision | Recall | F1 | PR-AUC |
| --- | ---: | ---: | ---: | ---: |
| Logistic regression | 0.80 | 0.85 | 0.82 | 0.84 |
| XGBoost | 0.99 | 0.99 | 0.99 | 0.99 |

Confusion matrix for XGBoost: 5,274 true alarms, 33 false alarms, 40 misses.

The average predicted probability is 0.018, which matches the 1.8% failure rate. So the probabilities are honest in aggregate. Machine by machine they sit near 0 or near 1. That is the simulator being loud, plus a calibration step that pushes scores to the ends. Do not promise a factory a 0.99.

**Remaining life, NASA FD001.** XGBoost RMSE is **19.5 cycles** against the official answer file, and **18.6 cycles** if you also cap the true answer at 125, which is how the model was trained. A linear regression on the raw sensors scores 21.9. The lift is real and modest. Error is worse when the engine still has a long life (23.4 RMSE past 125 cycles, versus 17.1 when fewer than 30 cycles remain).

**AI4I, any failure.** XGBoost F1 is **0.61**. Logistic regression is **0.28**. "Always say no failure" would be 96.6% accurate. Tool-wear failures are a miss (F1 about 0.07). Heat, power, and overstrain failures are much easier (F1 from 0.89 to 0.94).

**Morning list.** On 115 mornings, the top 10 had on average **2.49** machines that failed within 7 days. Oldest-machine-first had **1.50**. A random 10 had **1.25**. Ranking by probability alone also scored 2.49, because on this file the probability is already 0 or 1, so the business weights rarely change who is in the top 10. They do change the order among the machines that are already red.

## What is real, and what you made up

Real, in the sense of "published data, not invented in this repo":

- Hourly voltage, rotation, pressure, and vibration for 100 machines in 2015
- Error codes, component replacements, failure events, machine model, machine age

All three published datasets were simulated by their authors. Microsoft's file is a tutorial simulator. NASA's file is a turbofan simulator. AI4I is a synthetic milling process. There is no secret plant hiding in the repo.

Invented here, and labeled SIMULATED on the screen:

- Which line a machine sits on
- Production impact from 1 to 5 (seed 42, so it is the same every rebuild)
- Stock, reorder points, lead times
- The six technician names, skills, and shifts
- Work orders you create while clicking around

If someone says "so the whole thing is fake," the fair answer is: the failure model is fit to a published simulator with a real time split and a real baseline. The business half of the score is a placeholder a shop would replace with its own criticality ratings and its own storeroom.

## Why these three datasets

The Azure file is the plant. It has the shape of a small factory: machines, sensors, errors, repairs, failures. The dashboard lives on it.

C-MAPSS answers a different question, "how much life is left," on a dataset reviewers in this field recognize. It stops you from looking like you only know one classification demo.

AI4I is small, clean, and nasty in the way real maintenance data is nasty: almost every row is fine. It is there so you can talk about F1 without hand-waving.

## The data model, in one pass

Open `docs/schema.md` if you want the column map. The spoken version:

A **machine** has a model and an age from the file, plus a simulated line and impact. It emits **sensor readings**. It logs **faults** (error codes) and **failures** (a component actually broke). **Maintenance events** are component replacements. Historical ones are marked scheduled because the file does not say otherwise. A repair you log in the app is unscheduled and names a technician.

**Parts** and **technicians** are simulated. A **work order** is what you create from the queue. **Current scores** are the board at the plant clock. **Predictions** are the morning scores from September through December, used for the trend and the backtest.

Two extra tables, `bench_ai4i` and `bench_cmapss_fd001`, hold the other datasets so you can query them. They are not pretended to be machines in this plant. FD002 through FD004 come down in the NASA zip and stay on disk. The model is FD001 only: one operating condition, one fault mode.

The plant clock is the replay. The warehouse already has the whole year. The clock is "now." Anything after it is hidden. Moving the clock rescores. That is easier to explain than inserting 8,761 hours one at a time, and it cannot peek at the future.

## Why the splits are the way they are

**Azure: by time, not by row.** If you shuffle hours, Tuesday's row trains the model and Monday's row of the same failure tests it. The model has already seen the breakdown. Fit is January through July. August is not used to fit the trees. It is used to calibrate the probabilities and to pick the cutoff. September through December is touched once, for the reported numbers. That is stricter than fitting through August. Say so.

**C-MAPSS: by engine, not by row.** Each engine is one life. Random rows would put the middle of an engine in training and the end of the same engine in testing. Tuning uses grouped folds, three of them. The official test file is a different set of 100 engines and is scored once. The saved model is the one that won the cross-validation, not the one that looked best on the test file after the fact.

**AI4I: stratified random split.** These rows are not a time series. They are independent process snapshots. Stratified means the rare failures show up in both halves. Seed 42.

**Cycle number is not a feature on the turbines.** In the training file, a high cycle number means the engine is near death, because every engine is run until it fails. In the test file the series is cut off early, so a high cycle number does not mean the same thing. Using it would be a backdoor.

## Why not accuracy

Accuracy counts how often you are right. If 98% of hours are fine, a silent model is 98% accurate and useless to a maintenance lead. You care about two other things:

- **Precision:** of the alarms you raised, how many were real.
- **Recall:** of the real failures, how many you caught.
- **F1:** one number that punishes you if either of those is bad.
- **PR-AUC:** the same tradeoff across every cutoff, so you are not gaming a single threshold. It is the right curve when failures are rare. ROC curves look flattering on this problem.

The Azure threshold was chosen on August by best F1, then frozen. It landed at 1.0 because the calibrated scores are already at the extremes. That is a property of this simulator. Mention the logistic regression (F1 0.82, PR-AUC 0.84) as the number that shows the signal is real even without a fancy tree.

## The priority formula

```text
priority = P(fail in 24 hours) × impact × parts factor
```

Impact is 1 to 5. Parts factor is 1.5 if the needed part is out of stock or below its reorder point, otherwise 1.0.

Worked example, which the tests lock in: probability 0.40, impact 5, part out of stock.

`0.40 × 5 × 1.5 = 3.00`

Same machine with the part in stock: `2.00`.

This is not a fourth machine-learning model. It is a business weight. On the backtest it did not catch more failures than probability alone, because probability was already 0 or 1. That is a finding, not a failure of the demo. The weights still change which red machine is first when two machines are both about to fail and only one is out of stock. Machine 19 on the demo morning is that case: probability 1, impact 5, comp4 out of stock, priority 7.50.

The queue then applies a shop rule the backtest does not use. If any component was replaced in the last 24 hours, the queue score is 15% of the formula (`× 0.15`). Marking a machine repaired writes that replacement at the plant clock, rescores, and the machine drops. The probability stays on the page. You are not hiding the model. You are not sending a second technician to a machine someone just finished. Say that distinction. If you blur it, a sharp interviewer will think you cooked the backtest.

## This shift is a constraint, not a new model

On the demo morning the ranked list puts machine 19 first, at 7.50. The shift plan says do not start it. It is 06:00, so the day shift is on duty. Comp4 takes a general technician, and the only general technician works swing. Comp4 is also at zero on the shelf, with a 21-day lead time. The jobs that can start are machine 61 (E. Shah, hydraulics, one part left) and machine 77 (A. Rivera, mechanical).

Each person on duty can take one machine. A second job for the same skill waits. The code is `models/shift_plan.py`. The September–December backtest still ranks by the formula alone. If they ask why the top machine is not the one you work, that is the answer: priority says what hurts most, the shift plan says what this crew can touch before the part arrives.

## Why the 0.99 is not the boast

The Azure file was built so that failures leave a loud fingerprint in the sensors and the errors. A tree model can almost draw a box around them. The logistic regression is already good, which tells you the signal is simple. The component guess is essentially perfect for the same reason: the simulator's rule for "which component" is recoverable from the same features.

What transfers to a real shop is the method:

- time-based split
- a dumb baseline next to the real model
- F1 and PR-AUC
- probabilities checked against the base rate
- a business formula that is separate from the physics

What does not transfer is the 0.99. AI4I is the corrective. Same style of model, F1 0.61, and one failure mode it cannot see.

## Why remaining-life error is worse early

Training labels are capped at 125 cycles. A healthy engine is not allowed to have a target above that, so the model learns to sit near the cap until the sensors actually degrade. Test engines that still have a long official life therefore look "wrong" even when the model is behaving as trained. Report both RMSEs: 19.5 against the official file, 18.6 against the capped truth. The second matches the training target. The first is what the NASA file actually contains.

## What the repair button does

1. Closes the work order at the plant clock, not at your laptop's clock.
2. Writes an unscheduled maintenance row for that component, assigned to the simulated technician.
3. Decrements simulated stock by one, and refuses to go below zero.
4. Rescores every machine using only data up to the clock.
5. Because the replacement is inside 24 hours, the queue score is multiplied by 0.15.

The technician is chosen by a simulated skill map (comp1 mechanical, comp2 hydraulics, comp3 electrical, comp4 general), then by who has the fewest open jobs. The dataset does not say what those components are. The map is a stand-in.

## DuckDB instead of Postgres

The plan allows DuckDB when you do not want a database server. A reviewer can clone, download, and run without Docker. The schema is still SQL, with primary keys and foreign keys. Validation in Python is what actually rejects a bad file. DuckDB will not save you if you skip that.

If a real deployment needed multiple users writing at once, you would move the same schema to Postgres. The app talks to it through a small set of queries in `app/db.py`. That is the swap.

## What you would do with a real shop

Keep the tables. Replace the contents.

- Sensor readings come from their historian, at whatever grain they actually store. The 24-hour window assumes hourly data. If they log every minute, you aggregate first. The code checks that the Azure file really is hourly.
- Failures and work orders come from their CMMS. The failure table is the label. It must not be a feature.
- Impact comes from them: which machine stops which order. Delete the seeded 1-to-5 numbers.
- Parts come from their storeroom. Delete the four fake stock rows.
- Refit the 24-hour model on their history, with a time split. Expect the F1 to land closer to the AI4I result than to 0.99 until the data gets boring and clean.
- The C-MAPSS and AI4I models stay in the repo as proof. They do not score the shop's machines.

## What broke, and the fix

Use one of these if they ask for a scar.

1. **The Azure blob host did not resolve, and the NASA download failed an SSL handshake.** The script still tries the URLs in the plan first. It then uses Microsoft's own `sqlworkshops` mirror for the five CSVs, and the NASA PHM S3 bucket for C-MAPSS. That S3 file is a zip inside a zip. If every URL fails, the script tells you exactly which folder to drop the files into. No Kaggle key is required.

2. **DuckDB returned machine ids as 32-bit integers, and pandas refused to join them to 64-bit integers.** Feature building died on `merge_asof` after the models for the other two datasets had already trained. The fix is to cast ids and timestamps to one type before any join. There is a test that feeds int32 keys through the same function.

3. **The current XGBoost rejected string labels for the component model.** It wanted 0, 1, 2, 3. The component names are mapped to those integers and mapped back to `comp1`–`comp4` before anything is shown. The 24-hour model was unaffected. It was already 0/1.

## If they open a file

| They open | You say |
| --- | --- |
| `db/schema.sql` | The plant, the clock, the queue view. Simulated columns are called out. |
| `pipeline/validate.py` | What makes a bad file fail before it hits the database. |
| `pipeline/seed_ops.py` | The fake roster and the fake stock. Seed 42 for impact. |
| `models/features.py` | The only feature code. Training and the live clock both call it. |
| `models/azure_risk.py` | The 24-hour model, the months, the calibration. |
| `models/rul.py` | Engines, the cap at 125, why cycle number is absent. |
| `models/ai4i.py` | F1, the baseline, why RNF is not a target. |
| `models/priority.py` | The formula and the 24-hour shop rule. |
| `models/shift_plan.py` | Who is on duty, and which red machines cannot be started. |
| `models/score.py` | How a morning list is scored and how the backtest is counted. |
| `app/Home.py` | The screen a lead sees first. |
| `results/results.md` | The numbers. Do not recite from memory if this file is in front of you. |
| `tests/` | The formula example, the bad file, and the train/serve feature check. |

## Questions and short answers

**Is this an LLM wrapper?** No. scikit-learn and XGBoost. The reason text is built from the features and the stock rule, not generated by a chat model. The bars on the machine page are the tree model's own feature contributions.

**Why is the top machine first?** Read the reason on the row. Then check the arithmetic: probability times impact times 1 or 1.5. On the committed demo morning, machine 19 is probability 1, impact 5, comp4 out of stock, so 7.50.

**Did you leak the future into the model?** Labels look forward 24 hours. Features look backward. The test months are not in the fit. The dashboard hides rows after the plant clock. Failures are not a feature.

**Why is recall so high on Azure and so mixed on AI4I?** Different simulators. Azure's failure process is obvious in the sensors. AI4I's tool-wear failures are not. Quote both.

**What would a maintenance manager not trust?** The simulated stock, the simulated names, and a 0.99 that came from a tutorial simulator. The fix is their data in the same tables.

**What is next?** A real historian and a real CMMS mapped onto this schema, the seeded stock deleted, and the 24-hour model refit with a time split on their failures. The weights stay a starting point until a lead tells you what "impact" means in their plant.
