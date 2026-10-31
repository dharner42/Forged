"""Move the plant clock.

The warehouse already holds the full year. The clock is what the dashboard treats
as "now": live views hide rows after it, and the queue is rescored at that hour.
That is the replay. It is not 8,761 separate inserts.
"""

from __future__ import annotations

import argparse

import pandas as pd

from pipeline.warehouse import connect, read_clock


def main() -> None:
    parser = argparse.ArgumentParser(description="Move the Forge plant clock and rescore.")
    parser.add_argument("--as-of", help="Timestamp, for example 2015-11-16 06:00")
    parser.add_argument("--advance-hours", type=int, help="Move the current clock forward")
    args = parser.parse_args()

    from models.score import score_current

    if args.advance_hours is not None:
        con = connect()
        try:
            current = read_clock(con)
        finally:
            con.close()
        as_of = current + pd.Timedelta(hours=args.advance_hours)
    elif args.as_of:
        as_of = pd.Timestamp(args.as_of)
    else:
        parser.error("Pass --as-of or --advance-hours")

    score_current(as_of, note="Clock moved by pipeline.replay")
    print(f"Plant clock is now {pd.Timestamp(as_of)}")


if __name__ == "__main__":
    main()
