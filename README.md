# Industrial OI Platform — End-to-End IIoT Data Pipeline

A complete Industrial Operational Intelligence platform built from scratch,
demonstrating the full data journey from edge sensor to live dashboard.

> Built by an automation engineer who works daily with industrial systems —
> cranes, conveyors, PLCs — and wanted to build the data layer on top of
> them. Knowledge from this project was directly applied to deploy a
> TLS-secured MQTT broker in a live container terminal environment.

## Architecture

```
HP Laptop (edge)                  Main Laptop (data centre)
────────────────                  ─────────────────────────

factory_simulator
(Supervisor / Python)
        │
        │ MQTT  QoS 1
        ▼
                                  EMQX :1883
                                  (Docker)
                                        │
                                  mqtt_kafka_bridge.py
                                  (Supervisor / Python)
                                        │
                                        ▼
                                  Kafka :9092   ←── Zookeeper
                                  (Docker)
                                        │
                                  kafka_to_postgres.py
                                  (Supervisor / Python)
                                        │
                                        ▼
                                  PostgreSQL :5432
                                  public.machine_telemetry
                                        │
                                        │  dbt run (hourly)
                                        │  triggered by Airflow
                                        ▼
                                  analytics.stg_telemetry
                                  analytics.dim_machines
                                  analytics.fct_hourly_performance
                                        │
                                        ▼
                                  Grafana :3000
                                  Factory OI Dashboard (4 panels)
```

## Tech Stack

| Layer | Tool | Purpose |
|-------|------|---------|
| Edge | Python (paho-mqtt) | Simulates 3 industrial machines publishing MQTT telemetry |
| Transport | EMQX | MQTT broker — receives and fans out telemetry |
| Streaming | Apache Kafka + Zookeeper | Decoupled message buffer — no data loss on downstream failure |
| Storage | PostgreSQL 15 | Raw telemetry and analytics models |
| Transformation | dbt | SQL models with schema tests — staging, dimensions, hourly facts |
| Orchestration | Apache Airflow 2.9.0 | Hourly DAG: `dbt run` → `dbt test` |
| Visualisation | Grafana | Live dashboards querying PostgreSQL directly |
| Process Control | Supervisor | Manages Python pipeline services on both machines |
| Containerisation | Docker | All backend services, shared `factory-network` bridge |

## Repository Structure

```
iiot-oi-platform/
├── simulator/        ← edge device — three industrial machine simulators
├── pipeline/         ← Python scripts: MQTT→Kafka bridge and Kafka→PostgreSQL consumer
├── dbt/              ← analytics transformations (staging, dimension, fact models)
├── airflow/          ← DAG definitions for hourly orchestration
├── infrastructure/   ← Docker setup, Supervisor config, network architecture, startup procedure
├── grafana/          ← dashboard exports and panel documentation
├── docs/             ← architecture diagrams, project report, screenshots
└── demo/             ← interactive showcase site (GitHub Pages)
```

Each folder has its own README explaining what's inside and how it fits the architecture.

## Quick Start

This system runs across two laptops. See `infrastructure/README.md` for the
full setup, but the short version:

**Main laptop** — open WSL2, Supervisor auto-starts via `~/.bashrc`:
```bash
sudo supervisorctl status    # docker, mqtt_kafka_bridge, kafka_to_postgres — all RUNNING
docker ps                    # 7 containers Up
```

**HP laptop** — start the simulator:
```bash
sudo service supervisor start
sudo supervisorctl status    # factory_simulator — RUNNING
```

## What This Project Demonstrates

**Automation domain knowledge applied to data engineering.** The architecture
mirrors what real industrial data systems look like: MQTT at the edge, a
message broker as the central hub, Kafka for reliable buffering, and a
transformation layer feeding operational dashboards. It's not a tutorial
stack — it's the same pattern used in container terminals and manufacturing
plants.

Specific things worth pointing at:
- **Decoupled streaming** — MQTT → Kafka → PostgreSQL means no single point
  of failure; the simulator keeps publishing if the database goes down
- **Automated orchestration** — Airflow runs `dbt run` then `dbt test` hourly,
  and stops propagation to dashboards if data quality tests fail
- **Production debugging** — Kafka dual-listener configuration, WSL2 networking
  constraints, Airflow SQLite locking on WSL2, Docker container DNS resolution
  — real problems found and fixed

## Live Demo

[arcotkaran.github.io/iiot-oi-platform](https://arcotkaran.github.io/iiot-oi-platform/) —
interactive walkthrough with animated pipeline simulation.

## Author

**Karan Arcot** — Automation Engineer at Kalmar (Cargotec), specialising in
Industrial Operational Intelligence and data engineering.

[LinkedIn](https://www.linkedin.com/in/karanarcot/) · [GitHub](https://github.com/arcotkaran)

## License

MIT — see `LICENSE` for details.
