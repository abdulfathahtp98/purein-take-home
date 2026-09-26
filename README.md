# Pure-IN take-home: station sales in PostgreSQL
Loads the sample controller messages into PostgreSQL, produces daily sales
per station in Riyadh calendar days, and documents what in the data I
wouldn't trust at face value - and what I did about each thing.

## How to run it

```bash
# 1. Start Postgres
docker compose up -d

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create the schema
python scripts/run_migrations.py \
  --dsn postgresql://purein_admin:devpassword@localhost:5432/purein_task

# 4. Load the data (safe to run again -- see "Idempotency" below)
python scripts/load_messages.py \
  --dsn postgresql://purein_admin:devpassword@localhost:5432/purein_task

# 5. Daily sales per station
python scripts/daily_sales_report.py \
  --dsn postgresql://purein_admin:devpassword@localhost:5432/purein_task

# 6. The data-quality findings below, as actual queries
python scripts/data_quality_report.py \
  --dsn postgresql://purein_admin:devpassword@localhost:5432/purein_task

# 7. Automated tests (idempotency, per-pump keys, timezone safety)
TEST_DATABASE_URL=postgresql://purein_admin:devpassword@localhost:5432/purein_task \
  pytest -v
```

## The data at a glance

`messages.json` holds 113 deliveries containing 209 packets: 155 pump
sales and 54 tank readings, from 5 controllers, 13-16 Sept 2026. After
removing resends (finding #2) that is **151 unique sales and 52 unique tank
readings**.

## Schema

```mermaid
erDiagram
    stations ||--o{ controllers : has
    controllers ||--o{ raw_deliveries : sends
    raw_deliveries ||--o{ pump_transactions : contains
    raw_deliveries ||--o{ tank_readings : contains
```

- **stations / controllers** : from `stations.json`. `controllers` allows
  `station_id` and `utc_offset_minutes` to be `NULL`, on purpose (finding #1).
- **raw_deliveries** : every delivery received, stored once, keyed by a
  hash of its full content.
- **pump_transactions / tank_readings** : one row per packet, linked to the
  delivery it came from. Each keeps the controller's own timestamp as sent
  (`datetime_controller`) and the converted instant (`datetime_utc`,
  `TIMESTAMPTZ`).

## Idempotency (two layers)

1. **Delivery level.** Each delivery (`PtsId` + `Protocol` + `Packets`,
   canonicalized) is hashed and stored under a `UNIQUE content_hash`. An
   exact resend is skipped before any packet is touched.
2. **Business level** (migration `0007`). Sales are unique on
   `(pts_id, pump, transaction_no, datetime_controller)` and tank readings
   on `(pts_id, probe, datetime_controller)`, inserted with
   `ON CONFLICT DO NOTHING`. This catches a sale resent inside a *different*
   delivery (re-batched, renumbered packet Ids), which layer 1 alone would
   miss and double-count.

`tests/test_loader.py::test_loader_is_idempotent` runs the loader a second
time and asserts no row counts change.

Timestamps are converted with the controller's own offset into a
timezone-aware UTC value before insert, so results don't depend on the
database session's `TimeZone` setting 
`test_utc_conversion_does_not_depend_on_session_timezone` checks this with
the session set to `Asia/Riyadh`.

## Daily sales per station

Riyadh calendar days; SAR as reported by the controller.

| Station | 14 Sept | 15 Sept | 16 Sept |
|---|---|---|---|
| A | 623.05 L / 1,259.78 SAR | 363.44 L / 779.38 SAR | 358.84 L / 724.44 SAR |
| B | 506.54 L / 1,996.09 SAR* | 243.85 L / 514.38 SAR | 363.89 L / 749.38 SAR |
| C | 359.45 L / 769.96 SAR | 316.58 L / 680.43 SAR | 308.01 L / 637.84 SAR |
| D | 360.55 L / 745.00 SAR | 298.89 L / 637.82 SAR | 435.21 L / 876.12 SAR |

\* Includes the suspect 1,064.20 SAR amount (finding #4). With volume x
price for that sale instead, the day is 1,038.31 SAR. I report the figure as
sent and flag it rather than silently correcting financial data.

The unregistered controller's 3 sales (250.35 SAR) are listed separately by
`daily_sales_report.py`, not folded into any station.

## What I wouldn't trust in this data (and what I did about it)

`scripts/data_quality_report.py` reproduces every finding below as a query.

**1. One controller isn't registered.**
`PtsId 007706552332880992321564` sends 3 sales and 4 tank readings but
isn't in `stations.json`. Its rows are loaded and kept, with `station_id`
and `utc_offset_minutes` left `NULL`, and its sales are reported separately
rather than guessed into a station or dropped. Its tank readings fall at
06:0x and 18:0x on its own clock the same schedule as Stations A-C (see
#5) so its clock is very likely UTC+3. I still don't attribute it to a
station: that needs someone to confirm where it is installed.

**2. Two deliveries were resent byte-for-byte.** One from Station B (sale
7629 plus 2 tank readings) and one from Station D (sales 6227, 5358, 5359).
Both are skipped by the content hash; the natural keys would catch them
too.

**3. Transaction numbers are per-pump counters, not per-controller.**
At Station A, pump 1 issues 7407-7415 and pump 2 issues 7407-7414, so e.g.
txn 7407 is a 9.17 L sale on pump 1 *and* a separate 42.92 L sale on
pump 2. Every other pump has its own counter too. The data isn't wrong,
but `(PtsId, Transaction)`, the key that looks obvious, would silently
merge real sales and lose revenue. The correct key includes `Pump`. Within
`(PtsId, Pump, Transaction)` there are zero conflicts; the only repeats
are the resends in #2.

**4. One sale's `Amount` doesn't match `Volume x Price`.** Station B,
pump 4, txn 4997 (Diesel): `Amount = 1064.20` SAR, but
`64.11 L x 1.66 = 106.42` SAR a factor of 10, most likely a decimal-place
error upstream. Both `amount_reported` (as sent) and `amount_expected`
(computed with exact decimals) are stored; the report flags any gap over
0.02 SAR for someone to verify with the station.

**5. Station D's clock runs on UTC its offset of 0 is correct.**
Station D is the only controller registered with `utc_offset_minutes = 0`,
which looks like a metadata mistake at first. The data says otherwise: A,
B, C (and the unregistered controller) record tank readings at 06:0x and
18:0x on their own clocks; Station D records them at 03:0x and 15:0x 
the same schedule, shifted exactly 3 hours. Its sales hours are consistent
with the same shift (its morning peak sits at 02-04 on its clock vs 05-07
elsewhere). So D's timestamps are UTC and the offset is right. Worth
confirming once with whoever maintains `stations.json`, but I would not
"fix" it.

**6. Tank levels and recorded sales don't reconcile by 17-44x.**
Between each tank's first and last reading (about 2.5 days), tank volume
drops 7,000-11,000 L, while pump sales of that grade in the same window
total 190-490 L. Since per-pump transaction numbers are contiguous, sales
aren't missing from the feed. So either fuel is leaving the tanks without
going through a recorded pump sale, or the probe volumes are wrong. This is
the single biggest thing I wouldn't trust, and I'd raise it before anyone
uses these numbers for inventory or loss control.

**7. No tank probe covers Gasoline 95.** Probes only report Gasoline 91 and
Diesel, at every station, while Gasoline 95 is about 37% of sales. Those
sales can't be reconciled against anything.

**8. Water heights jump between readings.** For example Station A probe 1
goes 3.2 -> 0.0 -> 14.2 mm over consecutive readings. Real water in a tank
doesn't appear and disappear like that; I'd treat the water sensor as
noise until it's checked.

## What I'd add with more time

- A dry-run mode for the loader that reports what it *would* insert
- Alerting rather than just a report when a new amount mismatch or
  unreconciled tank drop appears
- Tank reconciliation that accounts for fuel drops (refills) between
  readings, once refill events are available

## AI tool use

Built with an AI assistant: schema design against the actual message
shapes, the loader and report scripts, and a pass across the full
`messages.json` to find anomalies. A second review pass, checking every
claim against the raw data, corrected my first diagnosis of finding #3
("numbers reused across days" -> per-pump counters), caught a row-count bug
in the data-quality report and a session-timezone dependency in the UTC
conversion, and surfaced findings #5-#8. Prompts are in `PROMPTS.md`.
