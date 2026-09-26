#!/usr/bin/env python3
"""
Applies every .sql file in migrations/, in filename order, that hasn't
already been recorded in schema_migrations.

Usage:
    python scripts/run_migrations.py --dsn postgresql://user:pass@host/db
"""
import argparse
import pathlib
import sys

import psycopg2

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "migrations"


def get_applied(conn) -> set:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.schema_migrations') IS NOT NULL")
        if not cur.fetchone()[0]:
            return set()
        cur.execute("SELECT version FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


def apply_migration(conn, path: pathlib.Path) -> None:
    with conn.cursor() as cur:
        cur.execute(path.read_text())
        cur.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.name,))
    conn.commit()
    print(f"applied {path.name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True)
    args = parser.parse_args()

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    conn = psycopg2.connect(args.dsn)
    try:
        applied = get_applied(conn)
        pending = [f for f in files if f.name not in applied]
        if not pending:
            print("database is up to date")
            return 0
        for f in pending:
            try:
                apply_migration(conn, f)
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                print(f"FAILED on {f.name}: {exc}", file=sys.stderr)
                return 1
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
