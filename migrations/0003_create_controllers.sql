-- 0003_create_controllers.sql
--
-- Controllers as registered in stations.json, keyed by their own PtsId.
--
-- station_id and utc_offset_minutes are both nullable: a controller can
-- send us data before (or without ever) being registered. Rather than
-- dropping that data, we still record it -- honestly marked as
-- unresolved -- instead of pretending we know things we don't.

CREATE TABLE controllers (
    pts_id               TEXT PRIMARY KEY,
    station_id           INTEGER REFERENCES stations(station_id),
    utc_offset_minutes   INTEGER,
    is_registered        BOOLEAN NOT NULL DEFAULT true,
    first_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
