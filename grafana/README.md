# Grafana — Live Dashboards

Grafana is the visualisation layer. It connects directly to PostgreSQL and
queries the `analytics` schema built by dbt — so every panel always reflects
the latest hourly transformation run.

## Dashboard: Factory OI Dashboard

Four panels covering the key operational signals:

| Panel | Query Source | What it shows |
|-------|-------------|----------------|
| Live temperatures | `analytics.stg_telemetry` | Real-time temperature per machine |
| Machine status | `analytics.dim_machines` | Running / idle / fault state |
| Hydraulic pressure | `analytics.stg_telemetry` | Pressure trend for hydraulic press |
| Hourly aggregates | `analytics.fct_hourly_performance` | KPIs rolled up per machine per hour |

## Data source

PostgreSQL datasource configured in Grafana:
- **Host:** `postgres:5432` (Docker container name)
- **Database:** `factory_db`
- **User:** `factory`

## Access

- Web UI: http://localhost:3000
- Default login: admin / (set at first login)

## Dashboard export

The dashboard JSON export belongs here — useful for restoring the dashboard
on a fresh Grafana instance without manually recreating panels. Export from
Grafana → Dashboard settings → JSON model, then save as `factory_oi_dashboard.json`.
