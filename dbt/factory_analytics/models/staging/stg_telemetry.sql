-- stg_telemetry.sql
-- Cleans and standardises raw machine telemetry
-- Combines temperature fields from different machines into one column

SELECT
    id,
    machine_id,
    mqtt_topic,
    COALESCE(temperature_c, oil_temp_c) AS temperature_c,
    spindle_rpm,
    vibration_mms,
    tool_wear_pct,
    belt_speed_mpm,
    motor_load_pct,
    running_hours,
    pressure_bar,
    oil_temp_c,
    cycle_count,
    status,
    fault,
    received_at,
    DATE_TRUNC('hour', received_at) AS hour_bucket
FROM public.machine_telemetry
WHERE machine_id IS NOT NULL
