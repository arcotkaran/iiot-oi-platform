# Industrial OI Platform — End-to-End IIoT Data Pipeline

A complete Industrial Operational Intelligence platform built from scratch,
covering the full data journey from edge sensors to live dashboards.

> Built by an automation engineer to bridge the gap between industrial systems
> and modern data engineering — directly applied at work to deploy a TLS-secured
> MQTT broker in a container terminal environment.

## Architecture
┌──────────────┐    ┌────────┐    ┌──────────────────┐    ┌────────┐    ┌──────────────────┐    ┌──────────┐    ┌─────────┐
│  Edge Device │───▶│  EMQX  │───▶│ MQTT-Kafka       │───▶│ Kafka  │───▶│ Kafka-Postgres   │───▶│PostgreSQL│───▶│ Grafana │
│  (HP Laptop) │    │ Broker │    │ Bridge (Python)  │    │ Topic  │    │ Consumer (Python)│    │  + dbt   │    │Dashboard│
└──────────────┘    └────────┘    └──────────────────┘    └────────┘    └──────────────────┘    └──────────┘    └─────────┘
▲
│
┌──────────────┐
│   Airflow    │
│ (hourly DAG) │
└──────────────┘

## Tech Stack

| Layer | Tool | Purpose |
|-------|------|---------|
| Edge | Python (paho-mqtt) | Simulates 3 industrial machines |
| Transport | EMQX | MQTT broker — receives telemetry |
| Streaming | Apache Kafka + Zookeeper | Buffers and distributes messages |
| Storage | PostgreSQL | Stores raw and transformed data |
| Transformation | dbt | SQL-based analytics models |
| Orchestration | Apache Airflow | Schedules dbt runs hourly |
| Visualisation | Grafana | Live dashboards |
| Process Control | Supervisor | Manages Python services |
| Containerisation | Docker | All services |

## Repository Structure
iiot-oi-platform/
├── simulator/        ← edge device — machine telemetry simulator
├── pipeline/         ← Python scripts moving data through the streaming layer
├── dbt/              ← analytics transformations
├── airflow/          ← orchestration DAGs
├── infrastructure/   ← Docker and Supervisor setup
├── grafana/          ← exported dashboards
├── docs/             ← architecture diagrams, project report, screenshots
└── demo/             ← interactive web demo (GitHub Pages)

Each subfolder has its own README explaining what's inside and why.

## Quick Start

This project runs across two laptops on the same network:
- **Main laptop** — runs all services (Docker containers + Python pipelines)
- **HP laptop** — runs the simulator (edge device)

See `infrastructure/README.md` for detailed setup instructions.

## What This Project Demonstrates

- **End-to-end data engineering** — from raw sensor data to live analytics
- **Production patterns** — message buffering, decoupled services, automated
  orchestration, data quality testing
- **Real industrial relevance** — the same architecture used in container
  terminals, manufacturing plants, and smart factories
- **Problem-solving** — production-level issues debugged and resolved
  (Kafka dual-listener configuration, WSL2 networking, Airflow backend
  migration, Docker network routing)

## Live Demo & Project Report

Visit the [project showcase](https://arcotkaran.github.io/iiot-oi-platform/)
for an interactive walkthrough and the full project report.

## Author

**Karan Arcot** — Automation Engineer specialising in Industrial Operational Intelligence and data engineering.

[LinkedIn](https://www.linkedin.com/in/karanarcot/)
[GitHub](https://github.com/arcotkaran)

## License

MIT — see `LICENSE` file for details.
