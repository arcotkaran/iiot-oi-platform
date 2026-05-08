# Infrastructure

The platform runs on Docker containers (managed via Docker's `--restart always`)
and Python processes (managed via Supervisor) across two laptops on the same
home network.

## Hardware

| Device | Role | OS | IP Address |
|--------|------|----|------------|
| Main Laptop | Data centre — runs all services | Windows 11 Pro 24H2 + WSL2 Ubuntu 24.04 | 192.168.0.25 (Ethernet) |
| HP Laptop | Edge device — machine simulator | Windows 11 Pro 24H2 + WSL2 Ubuntu 24.04 | 192.168.0.183 (WiFi) |
| Router | Network gateway | — | 192.168.0.1 |

## Docker Containers (Main Laptop)

All containers share the `factory-network` Docker bridge network and have
`--restart always` policy for automatic recovery on Docker restart.

| Service | Image | Port(s) | Purpose |
|---------|-------|---------|---------|
| EMQX | emqx/emqx:latest | 1883, 8083, 8084, 8883, 18083 | MQTT broker |
| Kafka | confluentinc/cp-kafka:7.5.0 | 9092 | Streaming platform |
| Zookeeper | confluentinc/cp-zookeeper:7.5.0 | 2181 (internal) | Kafka coordinator |
| PostgreSQL | postgres:15 | 5432 | Data warehouse |
| Grafana | grafana/grafana:latest | 3000 | Live dashboards |
| Airflow | apache/airflow:2.9.0 | 8080 | Pipeline orchestration |
| Node-RED | nodered/node-red:latest | 1880 | Visual flow editor (legacy) |

### Key Kafka Configuration

Kafka uses dual listeners to support both intra-Docker and external connections:
KAFKA_LISTENERS=PLAINTEXT_INTERNAL://0.0.0.0:29092,PLAINTEXT_EXTERNAL://0.0.0.0:9092
KAFKA_ADVERTISED_LISTENERS=PLAINTEXT_INTERNAL://kafka:29092,PLAINTEXT_EXTERNAL://localhost:9092
KAFKA_INTER_BROKER_LISTENER_NAME=PLAINTEXT_INTERNAL

### Airflow Configuration

Airflow runs in Docker (not via Supervisor) to isolate its dependencies from
dbt. It uses PostgreSQL as the metadata backend (not the default SQLite, which
has known locking issues on WSL2).
AIRFLOW__CORE__EXECUTOR=LocalExecutor
AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://airflow:airflow123@postgres/airflow_db

dbt is installed inside the Airflow container via:
docker exec airflow /home/airflow/.local/bin/pip install dbt-postgres

## Supervisor Processes — Main Laptop

Configuration: `/etc/supervisor/conf.d/factory.conf`
Web dashboard: http://localhost:9001 (admin / admin123)

| Process | Priority | Purpose |
|---------|----------|---------|
| `docker` | 1 | Starts Docker daemon at boot so all containers come up |
| `mqtt_kafka_bridge` | 10 | Python — subscribes to EMQX `factory/#`, publishes to Kafka `machine-telemetry` |
| `kafka_to_postgres` | 10 | Python — Kafka consumer (group `postgres-consumer`), writes to `public.machine_telemetry` |

Auto-start on Ubuntu open is configured via `~/.bashrc`:
```bash
sudo service supervisor status > /dev/null 2>&1 || sudo service supervisor start
```

## Supervisor Processes — HP Laptop (Edge Device)

Configuration: `/etc/supervisor/conf.d/simulator.conf`
Web dashboard: http://192.168.0.183:9002 (admin / admin123)

| Process | Purpose |
|---------|---------|
| `factory_simulator` | Publishes simulated telemetry for 3 machines every second |

## Network Architecture
HP Laptop (192.168.0.183)              Main Laptop (192.168.0.25)
─────────────────────────              ──────────────────────────
factory_simulator
(WSL2 / supervisor)
│
│ MQTT (paho-mqtt, QoS 1)
▼
EMQX :1883 / :18083
│
mqtt_kafka_bridge
(supervisor / Python)
│
│ Kafka producer
▼
Kafka :9092 ←──── Zookeeper :2181
│
kafka_to_postgres
(supervisor / Python)
│
│ INSERT
▼
PostgreSQL :5432
db: factory_db
schema: public.machine_telemetry
│
│ dbt run (hourly)
▼
PostgreSQL
schema: analytics
├── stg_telemetry
├── dim_machines
└── fct_hourly_performance
│
▼
Grafana :3000
Factory OI Dashboard
(4 panels)

## Port Forwarding (Windows netsh — Main Laptop)

WSL2's internal IP changes between restarts, so Windows port-forwards to it:

| External Port | Forwards To | Purpose |
|---------------|-------------|---------|
| 1883 | WSL2:1883 | MQTT — HP laptop simulator connects here |
| 9001 | WSL2:9001 | Supervisor web dashboard |
| 8080 | WSL2:8080 | Airflow web dashboard |

## Startup Procedure

### Main Laptop
```bash
wsl                          # Auto-runs supervisor start via ~/.bashrc
sudo supervisorctl status    # Verify 3 processes RUNNING
docker ps                    # Verify 7 containers Up
```

### HP Laptop
```bash
wsl
sudo service supervisor start
sudo supervisorctl status    # Verify factory_simulator RUNNING
```

Docker containers auto-start via `--restart always`.

## Database Schema

**Database:** `factory_db` | **User:** `factory` | **Password:** `factory123`

### Raw Layer (public schema)
- `public.machine_telemetry` — every individual reading
  - Indexes: `id` (PK), `machine_id`, `received_at`

### Analytics Layer (analytics schema, built by dbt)
- `analytics.stg_telemetry` — cleaned, standardised view
- `analytics.dim_machines` — machine master dimension
- `analytics.fct_hourly_performance` — hourly KPIs per machine

### Airflow Backend
- `airflow_db` (owner: `airflow`, password: `airflow123`)
