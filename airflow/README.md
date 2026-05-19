# airflow — Pipeline Orchestration

Schedules and monitors the dbt transformation pipeline. Without Airflow,
dbt models only update when triggered manually. With it, the analytics
layer refreshes automatically every hour, and failed runs are retried and
logged with a full audit trail.

## DAG: factory_dbt_hourly

`dags/factory_dbt_dag.py`

| Property | Value |
|----------|-------|
| Schedule | `@hourly` |
| Start date | 2026-04-28 |
| Catch-up | Disabled — only runs on the current interval, not historical gaps |
| Retries | 1 retry, 5-minute delay |
| Tags | `factory`, `dbt` |

Tasks (in order):

| Task | Operator | Command |
|------|----------|---------|
| `run_dbt_models` | BashOperator | `dbt run --profiles-dir /opt/airflow/.dbt --project-dir /opt/airflow/dbt` |
| `test_dbt_models` | BashOperator | `dbt test --profiles-dir /opt/airflow/.dbt --project-dir /opt/airflow/dbt` |

`run_dbt >> test_dbt` — tests only run if models succeed.

## Deployment

Airflow runs in Docker with PostgreSQL as the metadata backend. dbt is
installed inside the container.

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

Install dbt inside the container (one-time, after first start):
```bash
docker exec airflow /home/airflow/.local/bin/pip install dbt-postgres
```

## Why PostgreSQL as the metadata backend?

The default SQLite backend has known locking bugs on WSL2 that cause
Airflow's database migration to hang on startup. PostgreSQL avoids this
entirely — it also shares the existing `postgres` container, so no extra
service is needed.

## Access

- Web UI: http://localhost:8080
- Login: admin / (auto-generated — run `docker logs airflow | grep password`)
