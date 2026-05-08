# Pipeline — Streaming Data Movement

Two Python scripts that move data through the streaming layer:
EMQX → mqtt_kafka_bridge.py → Kafka → kafka_to_postgres.py → PostgreSQL

Both scripts run continuously as background services managed by Supervisor.

## mqtt_kafka_bridge.py

Subscribes to `factory/#` on EMQX and publishes every message to the Kafka
topic `machine-telemetry`.

| Setting | Value |
|---------|-------|
| MQTT broker | localhost:1883 |
| MQTT topic | factory/# (wildcard) |
| Client ID | factory-bridge |
| Kafka broker | localhost:9092 |
| Kafka topic | machine-telemetry |

The bridge wraps each MQTT message with metadata (source topic, timestamp)
before forwarding to Kafka — preserving traceability.

## kafka_to_postgres.py

Consumes from Kafka topic `machine-telemetry` and writes each message as a
row in `public.machine_telemetry`.

| Setting | Value |
|---------|-------|
| Kafka broker | localhost:9092 |
| Kafka topic | machine-telemetry |
| Consumer group | postgres-consumer |
| Database | factory_db |
| Table | public.machine_telemetry |

The consumer group ensures Kafka tracks the offset — if the script crashes and
restarts, it resumes from the last committed message with no data loss.

## Why Two Scripts Instead Of One?

Decoupling the broker from the database via Kafka provides:

- **Buffering** — if PostgreSQL goes down, Kafka retains messages until the
  consumer reconnects
- **Replayability** — Kafka stores messages on disk; new consumers can read
  historical data
- **Multiple consumers** — additional consumers (e.g. analytics streaming, ML
  inference) can subscribe to the same topic independently

## Running

Both scripts run as Supervisor services on the main laptop:

```bash
sudo supervisorctl status
# mqtt_kafka_bridge    RUNNING
# kafka_to_postgres    RUNNING
```

Manual run (for debugging):
```bash
python3 mqtt_kafka_bridge.py
python3 kafka_to_postgres.py
```

## Dependencies

- `paho-mqtt` — MQTT client
- `kafka-python` — Kafka producer/consumer
- `psycopg2-binary` — PostgreSQL driver
