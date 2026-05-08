# Airflow — Pipeline Orchestration

Schedules and monitors the dbt transformation pipeline.

## What Airflow Does Here

Without orchestration, dbt models only refresh when manually run. Airflow runs
`dbt run` and `dbt test` automatically every hour — keeping the analytics
layer continuously fresh.

## DAG: factory_dbt_hourly

| Task | Operator | Command |
|------|----------|---------|
| `run_dbt_models` | BashOperator | `dbt run --profiles-dir ... --project-dir ...` |
| `test_dbt_models` | BashOperator | `dbt test --profiles-dir ... --project-dir ...` |

Schedule: `@hourly`
Tags: `dbt`, `factory`

## Deployment

Airflow runs in Docker (image `apache/airflow:2.9.0`) with PostgreSQL as the
metadata backend. dbt is installed inside the Airflow container.

```bash
docker run -d \
  --name airflow \
  --network factory-network \
  --restart always \
  -p 8080:8080 \
  -e AIRFLOW__CORE__EXECUTOR=LocalExecutor \
  -e AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://airflow:airflow123@postgres/airflow_db \
  -e AIRFLOW__CORE__LOAD_EXAMPLES=False \
  -v ~/airflow/dags:/opt/airflow/dags \
  -v ~/factory_analytics:/opt/airflow/dbt \
  -v ~/.dbt:/opt/airflow/.dbt \
  apache/airflow:2.9.0 standalone
```

dbt installation (one-time, after first container start):
```bash
docker exec airflow /home/airflow/.local/bin/pip install dbt-postgres
```

## Why PostgreSQL Backend?

The default SQLite backend has known locking issues on WSL2 that cause Airflow
to hang during database migration. PostgreSQL avoids this entirely.

## Access

- Web UI: http://localhost:8080
- Login: admin / (auto-generated, see `docker logs airflow | grep password`)
