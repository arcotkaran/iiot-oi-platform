# dbt — Analytics Transformation Layer

Transforms raw machine telemetry into clean, tested analytics models inside
PostgreSQL. The dbt project lives at `dbt/factory_analytics/` and runs
inside the Airflow container every hour.

## Why dbt?

Raw streaming data arrives as JSON blobs, with inconsistent types and no
guarantees about field presence. dbt provides a transformation layer where
every model is version-controlled SQL, every field has a type contract, and
automated tests fail loudly before bad data reaches Grafana.

## Project structure

```
dbt/factory_analytics/
├── dbt_project.yml                          ← project config (target schema: analytics)
├── models/
│   ├── staging/
│   │   ├── stg_telemetry.sql               ← cleaned, standardised view
│   │   └── schema.yml                      ← schema tests
│   └── marts/
│       ├── dim_machines.sql                ← machine dimension
│       └── fct_hourly_performance.sql      ← hourly KPI fact table
└── tests/                                  ← custom data tests
```

## Data layers

| Layer | Schema | Materialization | Purpose |
|-------|--------|-----------------|---------|
| Raw | `public` | Table | Every reading from Kafka, exactly as received |
| Staging | `analytics` | View | Cleaned, typed, standardised |
| Marts | `analytics` | View | Star schema — dimensions and hourly facts |

All models are views so Grafana always queries the freshest data, not a
stale snapshot.

## Connection

Profile in `~/.dbt/profiles.yml`:
- **host:** `postgres` — Docker container name, required when dbt runs inside the Airflow container
- **dbname:** `factory_db`
- **schema:** `analytics`

Using `host: postgres` (not `localhost`) is the key networking detail here.

## Running

Manual:
```bash
cd ~/factory_analytics
dbt run
dbt test
```

Automated: the Airflow DAG `factory_dbt_hourly` runs `dbt run` then
`dbt test` every hour. See `airflow/README.md` for the deployment setup.

## Schema tests

- `unique` — primary keys have no duplicates
- `not_null` — required fields are always populated
- `accepted_values` — `machine_id` is one of the three known machines

When tests fail, the pipeline stops — preventing bad data from propagating
to dashboards.
