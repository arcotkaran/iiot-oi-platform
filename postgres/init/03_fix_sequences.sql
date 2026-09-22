-- Seeded rows keep their original IDs; move the ID counters past them
-- so new inserts from the pipeline don't collide.
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT a.attname AS col
    FROM pg_attribute a
    WHERE a.attrelid = 'public.machine_telemetry'::regclass
      AND a.attnum > 0 AND NOT a.attisdropped
      AND pg_get_serial_sequence('public.machine_telemetry', a.attname) IS NOT NULL
  LOOP
    EXECUTE format(
      'SELECT setval(pg_get_serial_sequence(%L, %L), COALESCE((SELECT MAX(%I) FROM public.machine_telemetry), 1))',
      'public.machine_telemetry', r.col, r.col);
  END LOOP;
END $$;
