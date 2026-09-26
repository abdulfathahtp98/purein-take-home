-- 0004_create_raw_deliveries.sql
--
-- Every delivery the server received, stored exactly once no matter how
-- many times a controller resends it. content_hash is a hash of the
-- full, canonicalized delivery payload (PtsId + Protocol + Packets).
--
-- This is what actually makes the loader idempotent: re-running it over
-- the same messages.json inserts zero new rows, because every delivery's
-- hash already exists. We dedupe at this transport layer -- not by
-- guessing which business field (like Transaction) is a reliable key,
-- because it turns out not to be (see README).

CREATE TABLE raw_deliveries (
    delivery_id    BIGSERIAL PRIMARY KEY,
    pts_id         TEXT NOT NULL REFERENCES controllers(pts_id),
    protocol       TEXT NOT NULL,
    content_hash   TEXT NOT NULL UNIQUE,
    raw_json       JSONB NOT NULL,
    received_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
