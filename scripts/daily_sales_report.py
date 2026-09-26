#!/usr/bin/env python3
"""
Daily sales per station, in liters and SAR, grouped by the Riyadh
calendar day.

Rows whose controller has no known UTC offset (unregistered controllers)
cannot be placed in any calendar day and are reported separately at the
end, rather than silently dropped or guessed at.

Usage:
    python scripts/daily_sales_report.py --dsn postgresql://user:pass@host/db
"""
import argparse

import psycopg2


REPORT_SQL = """
SELECT
    COALESCE(s.station_code, 'UNREGISTERED') AS station,
    (pt.datetime_utc AT TIME ZONE 'Asia/Riyadh')::date AS riyadh_day,
    ROUND(SUM(pt.volume), 2) AS liters,
    ROUND(SUM(pt.amount_reported), 2) AS sar_reported,
    COUNT(*) AS sale_count
FROM pump_transactions pt
JOIN controllers c ON c.pts_id = pt.pts_id
LEFT JOIN stations s ON s.station_id = c.station_id
WHERE pt.datetime_utc IS NOT NULL
GROUP BY 1, 2
ORDER BY 1, 2;
"""

UNRESOLVED_SQL = """
SELECT pt.pts_id, COUNT(*) AS sale_count, ROUND(SUM(pt.amount_reported), 2) AS sar_reported
FROM pump_transactions pt
WHERE pt.datetime_utc IS NULL
GROUP BY pt.pts_id;
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True)
    args = parser.parse_args()

    conn = psycopg2.connect(args.dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(REPORT_SQL)
            rows = cur.fetchall()

        print(f"{'Station':<14}{'Riyadh Day':<14}{'Liters':>10}{'SAR':>12}{'Sales':>8}")
        for station, day, liters, sar, count in rows:
            print(f"{station:<14}{str(day):<14}{liters:>10}{sar:>12}{count:>8}")

        with conn.cursor() as cur:
            cur.execute(UNRESOLVED_SQL)
            unresolved = cur.fetchall()

        if unresolved:
            print("\nExcluded (unknown clock offset, can't be placed in a Riyadh day):")
            for pts_id, count, sar in unresolved:
                print(f"  {pts_id}: {count} sales, {sar} SAR")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
