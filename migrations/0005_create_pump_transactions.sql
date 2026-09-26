-- 0005_create_pump_transactions.sql
--
-- One row per UploadPumpTransaction packet.
--
-- transaction_no is kept as-is from the controller, but it is NOT treated
-- as a global unique key: the same controller reuses transaction numbers
-- across days (see README), so two rows can legitimately share the same
-- transaction_no while being two different real sales.
--
-- amount_expected is volume * price, computed at load time, kept
-- alongside amount_reported (the untouched value from the controller) so
-- the two can be compared without ever silently rewriting financial data.

CREATE TABLE pump_transactions (
    pump_transaction_id  BIGSERIAL PRIMARY KEY,
    delivery_id          BIGINT NOT NULL REFERENCES raw_deliveries(delivery_id),
    pts_id               TEXT NOT NULL REFERENCES controllers(pts_id),
    pump                 TEXT NOT NULL,
    nozzle               TEXT NOT NULL,
    transaction_no       TEXT NOT NULL,
    fuel_grade_id        TEXT NOT NULL,
    fuel_grade_name      TEXT NOT NULL,
    volume               NUMERIC(10,3) NOT NULL CHECK (volume > 0),
    price                NUMERIC(10,4) NOT NULL CHECK (price > 0),
    amount_reported       NUMERIC(12,2) NOT NULL CHECK (amount_reported > 0),
    amount_expected        NUMERIC(12,2) NOT NULL,
    datetime_controller   TIMESTAMP NOT NULL,   -- as sent, on the controller's own clock
    datetime_utc          TIMESTAMPTZ           -- NULL when the controller's offset is unknown
);

CREATE INDEX idx_pump_transactions_pts_time ON pump_transactions(pts_id, datetime_utc);
