# pipeline — Streaming Layer

Two Python scripts that move data through the streaming layer. Together they
form the bridge between the MQTT broker and the database:

```
EMQX → mqtt_kafka_bridge.py → Kafka → kafka_to_postgres.py → PostgreSQL
```

Both run continuously as Supervisor services on the main laptop.

## mqtt_kafka_bridge.py

Subscribes to `factory/#` on EMQX (wildcard — catches all three machine
topics) and forwards every message to the Kafka topic `machine-telemetry`.

Each Kafka record wraps the original MQTT payload with metadata:
```json
{
  "mqtt_topic": "factory/cnc_mill/telemetry",
  "payload": { ... },
  "timestamp": 1716100000.0
}
```

| Setting | Value |
|---------|-------|
| MQTT broker | localhost:1883 |
| MQTT subscribe | `factory/#` |
| MQTT client ID | `factory-bridge` |
| Kafka broker | localhost:9092 |
| Kafka topic | `machine-telemetry` |

## kafka_to_postgres.py

Kafka consumer that reads from `machine-telemetry` and writes each message
as a row in `public.machine_telemetry`.

| Setting | Value |
|---------|-------|
| Kafka broker | localhost:9092 |
| Kafka topic | `machine-telemetry` |
| Consumer group | `postgres-consumer` |
| Database | `factory_db` |
| Table | `public.machine_telemetry` |

The consumer group tracks the Kafka offset. If the script crashes and
restarts (Supervisor handles this automatically), it resumes from the last
committed message — no data loss.

## Why two scripts instead of one?

Decoupling EMQX from PostgreSQL via Kafka provides three things that matter
in industrial systems:

- **Buffering** — if PostgreSQL goes down, Kafka retains messages on disk
  until the consumer reconnects
- **Replayability** — new consumers can read historical data from any offset;
  useful for backfilling analytics or replaying for ML model training
- **Fan-out** — additional consumers (streaming analytics, alerting, ML
  inference) can subscribe to the same Kafka topic independently without
  touching the main pipeline

## Running

Both scripts are managed by Supervisor on the main laptop:

```bash
sudo supervisorctl status
# docker              RUNNING
# mqtt_kafka_bridge   RUNNING
# kafka_to_postgres   RUNNING
```

To run manually for debugging:
```bash
python3 mqtt_kafka_bridge.py
python3 kafka_to_postgres.py
```

## Dependencies

- `paho-mqtt` — MQTT client (MQTT v5 CallbackAPIVersion)
- `kafka-python` — Kafka producer and consumer
- `psycopg2-binary` — PostgreSQL driver
