"""Deletes dialer data (call records, recordings, agent log and the APR days) older than N months.

    python purge_dialer_data.py --months 24            # shows how many rows would go
    python purge_dialer_data.py --months 24 --commit   # deletes them

Run it from cron (for example monthly) if you want to keep only a rolling window. It never touches CRM calls, tickets or customers.
"""
import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.database import engine


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, required=True, help="keep this many months")
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()
    if a.months < 3:
        raise SystemExit("Keep at least 3 months.")
    cutoff = datetime.now(timezone.utc) - timedelta(days=30 * a.months)
    jobs = [("call records", "cdr_calls", "start_at"), ("recordings", "cdr_recordings", "start_at"), ("agent log", "agent_log", "event_at"), ("APR days", "apr_daily", "last_at")]
    with engine.begin() as conn:
        for label, table, col in jobs:
            n = conn.execute(text(f"select count(*) from {table} where {col} < :c"), {"c": cutoff}).scalar()
            print(f"{label}: {n} older than {cutoff:%Y-%m-%d}")
            if a.commit and n:
                conn.execute(text(f"delete from {table} where {col} < :c"), {"c": cutoff})
    print("deleted" if a.commit else "nothing deleted (add --commit)")


if __name__ == "__main__":
    main()
