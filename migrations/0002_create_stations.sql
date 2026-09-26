-- 0002_create_stations.sql
CREATE TABLE stations (
    station_id    SERIAL PRIMARY KEY,
    station_code  TEXT NOT NULL UNIQUE,
    station_name  TEXT NOT NULL
);
