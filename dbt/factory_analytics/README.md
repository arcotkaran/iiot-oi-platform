# factory_analytics — dbt Project

This is the dbt project that transforms raw machine telemetry into clean
analytics models. It lives inside `dbt/factory_analytics/` and runs inside
the Airflow container every hour.

## Models

### Staging
`models/staging/stg_telemetry.sql` — cleans and standardises every row from
`public.machine_telemetry`. Casts types, renames fields to consistent
conventions, and filters out any malformed records before they reach the marts.

`models/staging/schema.yml` — schema tests: `unique`, `not_null`, and
`accepted_values` on `machine_id`.

### Marts
`models/marts/dim_machines.sql` — machine dimension table. One row per
machine with descriptive attributes. Lets Grafana queries join cleanly
without repeating string logic in every panel.

`models/marts/fct_hourly_performance.sql` — hourly KPI fact table. Aggregates
temperature, pressure, motor load, and running hours per machine per hour.
This is the primary table Grafana queries for trend panels.

## Running

From inside the Airflow container (or with dbt installed locally):
```bash
cd /opt/airflow/dbt
dbt run --profiles-dir /opt/airflow/.dbt --project-dir /opt/airflow/dbt
dbt test --profiles-dir /opt/airflow/.dbt --project-dir /opt/airflow/dbt
```

The Airflow DAG `factory_dbt_hourly` runs these commands automatically
every hour. See `airflow/README.md` for details.

## Profile

Connection lives in `~/.dbt/profiles.yml`:
- **host:** `postgres` — Docker container name, resolves inside `factory-network`
- **dbname:** `factory_db`
- **schema:** `analytics`

Using `host: postgres` (not `localhost`) is the key detail — it's required
for dbt to resolve the container when called from inside the Airflow container.
