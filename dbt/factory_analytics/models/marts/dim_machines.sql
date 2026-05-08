-- dim_machines.sql
-- One row per machine with metadata and current status

SELECT DISTINCT ON (machine_id)
    machine_id,
    CASE machine_id
        WHEN 'cnc_mill' THEN 'CNC Mill'
        WHEN 'conveyor' THEN 'Conveyor Belt'
        WHEN 'hydraulic_press' THEN 'Hydraulic Press'
        ELSE machine_id
    END AS machine_name,
    CASE machine_id
        WHEN 'cnc_mill' THEN 'Machining'
        WHEN 'conveyor' THEN 'Material Handling'
        WHEN 'hydraulic_press' THEN 'Press'
        ELSE 'Unknown'
    END AS machine_type,
    status AS current_status,
    fault AS current_fault,
    received_at AS last_seen
FROM public.machine_telemetry
ORDER BY machine_id, received_at DESC
