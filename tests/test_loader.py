"""
Run against a database that has already had the loader run on it ONCE.
test_loader_is_idempotent runs it a second time itself and checks nothing
changed -- this is the direct proof for task requirement #2.

Usage:
    TEST_DATABASE_URL=postgresql://... pytest -v
"""
import pathlib
import subprocess
import sys


PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _counts(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM raw_deliveries")
        deliveries = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM pump_transactions")
        pumps = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM tank_readings")
        probes = cur.fetchone()[0]
    return deliveries, pumps, probes


def test_loader_is_idempotent(conn, dsn):
    """Running the loader a second time must change nothing."""
    before = _counts(conn)

    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "load_messages.py"), "--dsn", dsn],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr

    after = _counts(conn)
    assert before == after, f"row counts changed on re-run: {before} -> {after}"


def test_no_pump_transaction_without_a_matching_delivery(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pt.pump_transaction_id
            FROM pump_transactions pt
            LEFT JOIN raw_deliveries rd ON rd.delivery_id = pt.delivery_id
            WHERE rd.delivery_id IS NULL
            """
        )
        orphans = cur.fetchall()
    assert orphans == []


def test_per_pump_transaction_numbers_were_not_collapsed(conn):
    """
    Transaction numbers are per-pump counters. At Station A, txn 7407 exists
    on pump 1 AND pump 2 as two different sales -- both must survive.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pump FROM pump_transactions
            WHERE pts_id = '007795293922342715931953' AND transaction_no = '7407'
            ORDER BY pump
            """
        )
        pumps = [r[0] for r in cur.fetchall()]
    assert pumps == ["1", "2"], f"expected one sale on each of pumps 1 and 2, found {pumps}"


def test_resent_sales_are_counted_once(conn):
    """151 unique sales / 52 unique tank readings after removing the resends."""
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM pump_transactions")
        sales = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM tank_readings")
        readings = cur.fetchone()[0]
    assert (sales, readings) == (151, 52)


def test_utc_conversion_does_not_depend_on_session_timezone(conn):
    """
    Station D (offset 0) sale txn 6221 on pump 4 happened at 23:25:16 on its
    own (UTC) clock on 13 Sept. Even with the session set to Riyadh time,
    the stored instant must be 23:25:16 UTC, i.e. 14 Sept in Riyadh.
    """
    with conn.cursor() as cur:
        cur.execute("SET TIME ZONE 'Asia/Riyadh'")
        cur.execute(
            """
            SELECT to_char(datetime_utc AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'),
                   (datetime_utc AT TIME ZONE 'Asia/Riyadh')::date::text
            FROM pump_transactions
            WHERE pts_id = '007756165832532719814330' AND pump = '4' AND transaction_no = '6221'
            """
        )
        utc, riyadh_day = cur.fetchone()
    assert utc == "2026-09-13 23:25:16"
    assert riyadh_day == "2026-09-14"


def test_amount_expected_is_always_populated(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM pump_transactions WHERE amount_expected IS NULL")
        missing = cur.fetchone()[0]
    assert missing == 0
