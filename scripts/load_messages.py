#!/usr/bin/env python3
"""
Loads stations.json and messages.json into PostgreSQL.

Idempotency strategy: each delivery (one item in messages.json) is hashed
in full -- PtsId, Protocol and Packets, canonicalized -- and stored once in
raw_deliveries under a UNIQUE content_hash. If a delivery's hash is already
present, none of its packets are re-processed. Running this script twice
over the same messages.json therefore inserts nothing new the second time.

Second layer: each sale is also unique on (pts_id, pump, transaction_no,
datetime_controller), and each tank reading on (pts_id, probe,
datetime_controller). That catches a sale resent inside a *different*
delivery, which the content hash alone would miss. Transaction numbers are
per-pump counters (see README, finding #3), so (PtsId, Transaction) on its
own is NOT a safe key -- it would wrongly merge sales from different pumps.

All datetimes are stored timezone-aware, so the result does not depend on
the database session's TimeZone setting.

Usage:
    python scripts/load_messages.py --dsn postgresql://user:pass@host/db
"""
import argparse
import datetime as dt
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import pathlib

import psycopg2
import psycopg2.extras

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"


def content_hash(delivery: dict) -> str:
    canonical = json.dumps(delivery, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_stations(conn, stations_path: pathlib.Path) -> None:
    stations = json.load(stations_path.open())["stations"]
    cur = conn.cursor()
    for s in stations:
        cur.execute(
            """
            INSERT INTO stations (station_code, station_name)
            VALUES (%s, %s)
            ON CONFLICT (station_code) DO NOTHING
            """,
            (s["station_code"], s["station_name"]),
        )
    conn.commit()

    cur.execute("SELECT station_code, station_id FROM stations")
    station_id_by_code = dict(cur.fetchall())

    for s in stations:
        cur.execute(
            """
            INSERT INTO controllers (pts_id, station_id, utc_offset_minutes, is_registered)
            VALUES (%s, %s, %s, true)
            ON CONFLICT (pts_id) DO UPDATE SET
                station_id = EXCLUDED.station_id,
                utc_offset_minutes = EXCLUDED.utc_offset_minutes,
                is_registered = true
            """,
            (s["pts_id"], station_id_by_code[s["station_code"]], s["utc_offset_minutes"]),
        )
    conn.commit()
    print(f"stations: {len(stations)} registered")


def ensure_controller(conn, pts_id: str) -> None:
    """Record any controller we see, even if it was never in stations.json."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO controllers (pts_id, station_id, utc_offset_minutes, is_registered)
            VALUES (%s, NULL, NULL, false)
            ON CONFLICT (pts_id) DO NOTHING
            """,
            (pts_id,),
        )
    conn.commit()


def get_offset_minutes(conn, pts_id: str):
    with conn.cursor() as cur:
        cur.execute("SELECT utc_offset_minutes FROM controllers WHERE pts_id = %s", (pts_id,))
        row = cur.fetchone()
        return row[0] if row else None


def to_utc(datetime_controller: dt.datetime, offset_minutes):
    """
    Attach the controller's own offset, then convert to UTC. Returns an
    AWARE datetime: a naive one written to a TIMESTAMPTZ column would be
    interpreted in the DB session's TimeZone, silently shifting every sale
    on any server not set to UTC.
    """
    if offset_minutes is None:
        return None
    local = datetime_controller.replace(
        tzinfo=dt.timezone(dt.timedelta(minutes=offset_minutes))
    )
    return local.astimezone(dt.timezone.utc)


def dec(value) -> Decimal:
    """JSON numbers arrive as floats; go via str to avoid float artefacts."""
    return Decimal(str(value))


def load_messages(conn, messages_path: pathlib.Path) -> None:
    deliveries = json.load(messages_path.open())

    seen_pts_ids = set()
    new_deliveries = 0
    skipped_duplicate_deliveries = 0
    pump_rows = 0
    probe_rows = 0
    skipped_pump_rows = 0
    skipped_probe_rows = 0

    for delivery in deliveries:
        pts_id = delivery["PtsId"]
        if pts_id not in seen_pts_ids:
            ensure_controller(conn, pts_id)
            seen_pts_ids.add(pts_id)

        offset_minutes = get_offset_minutes(conn, pts_id)
        h = content_hash(delivery)

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO raw_deliveries (pts_id, protocol, content_hash, raw_json)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (content_hash) DO NOTHING
                RETURNING delivery_id
                """,
                (pts_id, delivery["Protocol"], h, psycopg2.extras.Json(delivery)),
            )
            row = cur.fetchone()

        if row is None:
            skipped_duplicate_deliveries += 1
            conn.commit()
            continue

        delivery_id = row[0]
        new_deliveries += 1

        for packet in delivery["Packets"]:
            data = packet["Data"]
            dt_controller = dt.datetime.fromisoformat(data["DateTime"])
            dt_utc = to_utc(dt_controller, offset_minutes)

            if packet["Type"] == "UploadPumpTransaction":
                amount_expected = (dec(data["Volume"]) * dec(data["Price"])).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO pump_transactions
                            (delivery_id, pts_id, pump, nozzle, transaction_no,
                             fuel_grade_id, fuel_grade_name, volume, price,
                             amount_reported, amount_expected,
                             datetime_controller, datetime_utc)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT ON CONSTRAINT uq_pump_transactions_natural DO NOTHING
                        """,
                        (
                            delivery_id, pts_id, data["Pump"], data["Nozzle"], data["Transaction"],
                            data["FuelGradeId"], data["FuelGradeName"], dec(data["Volume"]),
                            dec(data["Price"]), dec(data["Amount"]), amount_expected,
                            dt_controller, dt_utc,
                        ),
                    )
                    if cur.rowcount == 1:
                        pump_rows += 1
                    else:
                        skipped_pump_rows += 1

            elif packet["Type"] == "ProbeMeasurements":
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO tank_readings
                            (delivery_id, pts_id, probe, fuel_grade_id, fuel_grade_name,
                             status, product_height, water_height, temperature,
                             product_volume, tank_filling_percentage,
                             datetime_controller, datetime_utc)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT ON CONSTRAINT uq_tank_readings_natural DO NOTHING
                        """,
                        (
                            delivery_id, pts_id, data["Probe"], data["FuelGradeId"], data["FuelGradeName"],
                            data["Status"], data.get("ProductHeight"), data.get("WaterHeight"),
                            data.get("Temperature"), data["ProductVolume"],
                            data.get("TankFillingPercentage"), dt_controller, dt_utc,
                        ),
                    )
                    if cur.rowcount == 1:
                        probe_rows += 1
                    else:
                        skipped_probe_rows += 1

        conn.commit()

    print(
        f"deliveries: {new_deliveries} new, {skipped_duplicate_deliveries} already loaded "
        f"(exact resends, safely skipped)"
    )
    print(f"pump_transactions inserted: {pump_rows} (skipped as already loaded: {skipped_pump_rows})")
    print(f"tank_readings inserted: {probe_rows} (skipped as already loaded: {skipped_probe_rows})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--stations", default=str(DATA_DIR / "stations.json"))
    parser.add_argument("--messages", default=str(DATA_DIR / "messages.json"))
    args = parser.parse_args()

    conn = psycopg2.connect(args.dsn)
    try:
        load_stations(conn, pathlib.Path(args.stations))
        load_messages(conn, pathlib.Path(args.messages))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
