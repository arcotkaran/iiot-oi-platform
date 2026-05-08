-- fct_hourly_performance.sql
-- Hourly aggregates per machine for dashboard and analytics

SELECT
    machine_id,
    DATE_TRUNC('hour', received_at) AS hour_bucket,
    COUNT(*) AS reading_count,
    ROUND(AVG(COALESCE(temperature_c, oil_temp_c))::numeric, 2) AS avg_temp_c,
    ROUND(MAX(COALESCE(temperature_c, oil_temp_c))::numeric, 2) AS max_temp_c,
    ROUND(MIN(COALESCE(temperature_c, oil_temp_c))::numeric, 2) AS min_temp_c,
    ROUND(AVG(spindle_rpm)::numeric, 1) AS avg_spindle_rpm,
    ROUND(AVG(vibration_mms)::numeric, 3) AS avg_vibration_mms,
    ROUND(AVG(belt_speed_mpm)::numeric, 2) AS avg_belt_speed,
    ROUND(AVG(motor_load_pct)::numeric, 1) AS avg_motor_load,
    ROUND(AVG(pressure_bar)::numeric, 1) AS avg_pressure_bar,
    MAX(cycle_count) AS max_cycle_count,
    COUNT(CASE WHEN fault IS NOT NULL THEN 1 END) AS fault_count,
    COUNT(CASE WHEN status = 'running' THEN 1 END) AS running_count,
    COUNT(CASE WHEN status = 'stopped' THEN 1 END) AS stopped_count
FROM public.machine_telemetry
GROUP BY machine_id, DATE_TRUNC('hour', received_at)
ORDER BY machine_id, hour_bucket
