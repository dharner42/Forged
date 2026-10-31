"""Train all three models and write the morning queue."""

from __future__ import annotations

import time

from models.ai4i import train_ai4i
from models.azure_risk import train_azure
from models.reporting import write_results
from models.rul import train_rul
from models.score import publish_scores


def main() -> None:
    started = time.perf_counter()
    print("== C-MAPSS FD001 remaining life ==")
    rul = train_rul()
    print(f"  winner {rul['winner']} in {time.perf_counter() - started:.0f}s")

    mark = time.perf_counter()
    print("== AI4I failure classifier ==")
    ai4i = train_ai4i()
    print(f"  XGBoost F1 {ai4i['xgboost_f1']:.3f} vs logistic {ai4i['logistic_f1']:.3f} ({time.perf_counter() - mark:.0f}s)")

    mark = time.perf_counter()
    print("== Azure 24-hour failure risk ==")
    azure = train_azure()
    print("== Scoring the morning queue ==")
    backtest = publish_scores(azure)
    print("  " + backtest["sentence"])
    print(f"  demo clock {backtest['demo_as_of']}")
    write_results(rul, ai4i, azure, backtest)
    # The feature frame is large and should not be kept after the report is written.
    azure.pop("frame", None)
    print(f"Finished in {(time.perf_counter() - started) / 60:.1f} min. See results/results.md")


if __name__ == "__main__":
    main()
