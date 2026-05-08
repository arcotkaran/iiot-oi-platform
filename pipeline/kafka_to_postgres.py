import json
import psycopg2
from kafka import KafkaConsumer

# ============================================================
# CONFIGURATION
# ============================================================
KAFKA_BROKER = "localhost:9092"
KAFKA_TOPIC = "machine-telemetry"
KAFKA_GROUP = "postgres-consumer"

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "factory_db",
    "user": "factory",
    "password": "factory123"
}

# ============================================================
# CONNECT TO POSTGRESQL
# ============================================================
print("Connecting to PostgreSQL...")
conn = psycopg2.connect(**DB_CONFIG)
cursor = conn.cursor()
print("PostgreSQL connected!")

# ============================================================
# CONNECT TO KAFKA
# ============================================================
print("Connecting to Kafka...")
consumer = KafkaConsumer(
    KAFKA_TOPIC,
    bootstrap_servers=KAFKA_BROKER,
    group_id=KAFKA_GROUP,
    value_deserializer=lambda v: json.loads(v.decode('utf-8')),
    auto_offset_reset='latest',
    api_version=(2, 5, 0)
)
print("Kafka connected!")
print("Listening for messages... (Ctrl+C to stop)\n")

# ============================================================
# INSERT FUNCTION
# ============================================================
def insert_record(record):
    payload = record.get("payload", {})
    machine_id = payload.get("machine_id", "unknown")

    cursor.execute("""
        INSERT INTO machine_telemetry (
            machine_id, mqtt_topic,
            temperature_c, spindle_rpm, vibration_mms, tool_wear_pct,
            belt_speed_mpm, motor_load_pct, running_hours,
            pressure_bar, oil_temp_c, cycle_count,
            status, fault
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        machine_id,
        record.get("mqtt_topic"),
        payload.get("temperature_c"),
        payload.get("spindle_rpm"),
        payload.get("vibration_mms"),
        payload.get("tool_wear_pct"),
        payload.get("belt_speed_mpm"),
        payload.get("motor_load_pct"),
        payload.get("running_hours"),
        payload.get("pressure_bar"),
        payload.get("oil_temp_c"),
        payload.get("cycle_count"),
        payload.get("status"),
        payload.get("fault")
    ))
    conn.commit()

# ============================================================
# MAIN LOOP
# ============================================================
count = 0
try:
    for message in consumer:
        record = message.value
        insert_record(record)
        count += 1
        machine = record.get("payload", {}).get("machine_id", "?")
        if count % 10 == 0:
            print(f"✅ {count} records saved | last: {machine}")

except KeyboardInterrupt:
    print(f"\nStopped. Total records saved: {count}")
finally:
    cursor.close()
    conn.close()
    consumer.close()
