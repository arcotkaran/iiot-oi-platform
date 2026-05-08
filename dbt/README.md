# dbt — Data Build Tool

Transforms raw machine telemetry into clean analytics models in PostgreSQL.

## Why dbt?

Raw streaming data is messy. dbt provides a transformation layer with version
control, automated testing, and documentation — all written in SQL.

## Project Structure
factory_analytics/
├── dbt_project.yml          ← project config
├── models/
│   ├── staging/
│   │   └── stg_telemetry.sql       ← cleaned, standardised view
│   └── marts/
│       ├── dim_machines.sql        ← machine master dimension
│       └── fct_hourly_performance.sql  ← hourly KPIs per machine
└── tests/                   ← schema and data quality tests

## Data Layers

| Layer | Schema | Materialization | Purpose |
|-------|--------|-----------------|---------|
| Raw | public | Table | Every reading from Kafka |
| Staging | analytics | View | Cleaned and standardised |
| Marts | analytics | View | Star schema dimensions and facts |

All models materialized as views so they always reflect the latest data — ideal
for streaming pipelines.

## Connection

Profile lives in `~/.dbt/profiles.yml`:
- **host:** `postgres` (Docker container name, resolves inside factory-network)
- **port:** 5432
- **user:** factory
- **dbname:** factory_db
- **schema:** analytics

## Running

Manual:
```bash
cd ~/factory_analytics
dbt run
dbt test
```

Automated: Airflow DAG `factory_dbt_hourly` runs `dbt run` and `dbt test`
every hour.

## Tests

- `unique` — primary keys are unique
- `not_null` — required fields are populated
- `accepted_values` — categorical fields contain only valid values

When tests fail, the pipeline stops — preventing bad data from reaching dashboards.
