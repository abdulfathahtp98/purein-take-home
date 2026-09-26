#!/usr/bin/env python3
"""
Surfaces the data-quality findings from the README as actual queries --
not just prose. Section numbers match the README's finding numbers.
(Finding #2, exact resends, is reported by the loader itself.)

Usage:
    python scripts/data_quality_report.py --dsn postgresql://user:pass@host/db
"""
import argparse

import psycopg2

STATION = "COALESCE(s.station_code, 'UNREGISTERED')"

# COUNT(DISTINCT ...) matters: joining both child tables onto controllers
# multiplies rows (3 sales x 4 readings = 12 rows), so a plain COUNT would
# report 12 and 12.
UNREGISTERED_SQL = """
SELECT c.pts_id,
       COUNT(DISTINCT pt.pump_transaction_id) AS sales,
       COUNT(DISTINCT tr.tank_reading_id)     AS readings
FROM controllers c
LEFT JOIN pump_transactions pt ON pt.pts_id = c.pts_id
LEFT JOIN tank_readings tr     ON tr.pts_id = c.pts_id
WHERE c.is_registered = false
GROUP BY c.pts_id;
"""

SHARED_TXN_NO_SQL = f"""
SELECT {STATION} AS station, pt.transaction_no,
       string_agg(DISTINCT pt.pump, ', ' ORDER BY pt.pump) AS pumps
FROM pump_transactions pt
JOIN controllers c ON c.pts_id = pt.pts_id
LEFT JOIN stations s ON s.station_id = c.station_id
GROUP BY 1, 2
HAVING COUNT(DISTINCT pt.pump) > 1
ORDER BY 1, 2;
"""

AMOUNT_MISMATCH_SQL = f"""
SELECT {STATION} AS station, pt.pump, pt.transaction_no, pt.volume, pt.price,
       pt.amount_reported, pt.amount_expected
FROM pump_transactions pt
JOIN controllers c ON c.pts_id = pt.pts_id
LEFT JOIN stations s ON s.station_id = c.station_id
WHERE ABS(pt.amount_reported - pt.amount_expected) > 0.02
ORDER BY ABS(pt.amount_reported - pt.amount_expected) DESC;
"""

# Tank readings run on a fixed schedule. Comparing the hour each controller
# stamps them with (on its own clock) against its registered offset is
# direct evidence of whether the offset is right.
CLOCK_EVIDENCE_SQL = f"""
SELECT {STATION} AS station, c.utc_offset_minutes,
       string_agg(DISTINCT to_char(tr.datetime_controller, 'HH24'), ', ') AS reading_hours_on_own_clock,
       string_agg(DISTINCT to_char(tr.datetime_utc AT TIME ZONE 'UTC', 'HH24'), ', ') AS reading_hours_utc
FROM controllers c
JOIN tank_readings tr ON tr.pts_id = c.pts_id
LEFT JOIN stations s ON s.station_id = c.station_id
GROUP BY 1, 2
ORDER BY 1;
"""

# Tank volume drop between first and last reading vs litres sold in that
# same window, per controller and grade. Uses the controller's own clock so
# it works for the unregistered controller too. Assumes one probe per grade,
# which holds in this dataset.
TANK_RECONCILIATION_SQL = f"""
WITH win AS (
    SELECT pts_id, fuel_grade_id, fuel_grade_name,
           MIN(datetime_controller) AS t0, MAX(datetime_controller) AS t1
    FROM tank_readings
    GROUP BY 1, 2, 3
), vols AS (
    SELECT w.*,
           (SELECT product_volume FROM tank_readings x
             WHERE x.pts_id = w.pts_id AND x.fuel_grade_id = w.fuel_grade_id
               AND x.datetime_controller = w.t0 LIMIT 1) AS v0,
           (SELECT product_volume FROM tank_readings x
             WHERE x.pts_id = w.pts_id AND x.fuel_grade_id = w.fuel_grade_id
               AND x.datetime_controller = w.t1 LIMIT 1) AS v1
    FROM win w
)
SELECT {STATION} AS station, v.fuel_grade_name, v.t0, v.t1,
       ROUND(v.v0 - v.v1, 0) AS tank_drop_l,
       ROUND(COALESCE((
           SELECT SUM(pt.volume) FROM pump_transactions pt
           WHERE pt.pts_id = v.pts_id AND pt.fuel_grade_id = v.fuel_grade_id
             AND pt.datetime_controller BETWEEN v.t0 AND v.t1
       ), 0), 0) AS sold_l
FROM vols v
JOIN controllers c ON c.pts_id = v.pts_id
LEFT JOIN stations s ON s.station_id = c.station_id
ORDER BY 1, 2;
"""

GRADE_WITHOUT_PROBE_SQL = f"""
SELECT DISTINCT {STATION} AS station, pt.fuel_grade_name
FROM pump_transactions pt
JOIN controllers c ON c.pts_id = pt.pts_id
LEFT JOIN stations s ON s.station_id = c.station_id
WHERE NOT EXISTS (
    SELECT 1 FROM tank_readings tr
    WHERE tr.pts_id = pt.pts_id AND tr.fuel_grade_id = pt.fuel_grade_id
)
ORDER BY 1, 2;
"""

WATER_JUMPS_SQL = f"""
WITH w AS (
    SELECT pts_id, probe, water_height,
           water_height - LAG(water_height) OVER (
               PARTITION BY pts_id, probe ORDER BY datetime_controller
           ) AS delta
    FROM tank_readings
)
SELECT {STATION} AS station, w.probe,
       COUNT(*) FILTER (WHERE ABS(w.delta) > 5) AS jumps_over_5mm,
       MAX(ABS(w.delta)) AS largest_jump_mm
FROM w
JOIN controllers c ON c.pts_id = w.pts_id
LEFT JOIN stations s ON s.station_id = c.station_id
GROUP BY 1, 2
HAVING COUNT(*) FILTER (WHERE ABS(w.delta) > 5) > 0
ORDER BY 1, 2;
"""


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def run(cur, sql):
    cur.execute(sql)
    rows = cur.fetchall()
    if not rows:
        print("  none found")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True)
    args = parser.parse_args()

    conn = psycopg2.connect(args.dsn)
    try:
        cur = conn.cursor()

        section("1. Unregistered controllers (can't be attributed to a station)")
        for pts_id, sales, readings in run(cur, UNREGISTERED_SQL):
            print(f"  {pts_id}: {sales} sales, {readings} tank readings -- needs registering")

        section("3. Transaction numbers shared across pumps (per-pump counters -- expected)")
        for station, txn_no, pumps in run(cur, SHARED_TXN_NO_SQL):
            print(f"  Station {station} txn#{txn_no}: used by pumps {pumps}")
        print("  -> (PtsId, Transaction) is not a unique key; (PtsId, Pump, Transaction) is.")

        section("4. Sales where Amount doesn't match Volume x Price (>0.02 SAR off)")
        for station, pump, txn_no, vol, price, reported, expected in run(cur, AMOUNT_MISMATCH_SQL):
            print(
                f"  Station {station} pump {pump} txn#{txn_no}: reported={reported} SAR, "
                f"expected={expected} SAR ({vol} L x {price}) -- verify with the station"
            )

        section("5. Controller clocks: tank-reading hours vs registered offset")
        for station, offset, own_hours, utc_hours in run(cur, CLOCK_EVIDENCE_SQL):
            print(
                f"  Station {station}: offset={offset} min, readings at {own_hours} "
                f"on its own clock, {utc_hours or 'n/a'} UTC"
            )
        print("  -> If every station reads tanks on the same schedule, their UTC hours should match.")

        section("6. Tank volume drop vs litres sold in the same window")
        for station, grade, t0, t1, drop, sold in run(cur, TANK_RECONCILIATION_SQL):
            ratio = f"{drop / sold:.0f}x" if sold else "n/a"
            print(f"  Station {station} {grade}: tank -{drop} L, sold {sold} L ({ratio}) [{t0} -> {t1}]")

        section("7. Grades sold with no tank probe to reconcile against")
        for station, grade in run(cur, GRADE_WITHOUT_PROBE_SQL):
            print(f"  Station {station}: {grade}")

        section("8. Water height jumping between consecutive readings (>5 mm)")
        for station, probe, jumps, largest in run(cur, WATER_JUMPS_SQL):
            print(f"  Station {station} probe {probe}: {jumps} jumps, largest {largest} mm")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
