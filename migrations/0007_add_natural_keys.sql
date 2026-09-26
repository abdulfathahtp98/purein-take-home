-- 0007_add_natural_keys.sql
--
-- Second layer of dedupe, at the business level.
--
-- The content hash on raw_deliveries only catches byte-identical resends.
-- If a controller re-batches an already-sent sale into a different
-- delivery (different packet Ids or neighbours), the hash differs and the
-- sale would be counted twice. These keys stop that.
--
-- Transaction numbers are per-pump counters, not per-controller: at
-- Station A, pumps 1 and 2 both issue 7407-7414. So the key must include
-- pump. datetime_controller is included as a guard against a counter
-- wrapping or being reset on a pump.

ALTER TABLE pump_transactions
    ADD CONSTRAINT uq_pump_transactions_natural
    UNIQUE (pts_id, pump, transaction_no, datetime_controller);

ALTER TABLE tank_readings
    ADD CONSTRAINT uq_tank_readings_natural
    UNIQUE (pts_id, probe, datetime_controller);
