-- 0006_create_tank_readings.sql
CREATE TABLE tank_readings (
    tank_reading_id          BIGSERIAL PRIMARY KEY,
    delivery_id              BIGINT NOT NULL REFERENCES raw_deliveries(delivery_id),
    pts_id                   TEXT NOT NULL REFERENCES controllers(pts_id),
    probe                    TEXT NOT NULL,
    fuel_grade_id            TEXT NOT NULL,
    fuel_grade_name          TEXT NOT NULL,
    status                   TEXT NOT NULL,
    product_height           NUMERIC(10,2),
    water_height             NUMERIC(10,2),
    temperature              NUMERIC(6,2),
    product_volume           NUMERIC(12,2) NOT NULL CHECK (product_volume >= 0),
    tank_filling_percentage  NUMERIC(5,2),
    datetime_controller      TIMESTAMP NOT NULL,
    datetime_utc             TIMESTAMPTZ
);

CREATE INDEX idx_tank_readings_pts_time ON tank_readings(pts_id, datetime_utc);
