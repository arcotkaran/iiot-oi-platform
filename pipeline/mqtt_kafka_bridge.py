import paho.mqtt.client as mqtt
from kafka import KafkaProducer
import json
import time

# ============================================================
# CONFIGURATION
# ============================================================
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
KAFKA_BROKER = "localhost:9092"
KAFKA_TOPIC = "machine-telemetry"

# ============================================================
# CONNECT TO KAFKA
# ============================================================
print("Connecting to Kafka...")
producer = KafkaProducer(
    bootstrap_servers='localhost:9092',
    value_serializer=lambda v: json.dumps(v).encode('utf-8'),
    api_version=(2, 5, 0),
    request_timeout_ms=30000,
    metadata_max_age_ms=10000
)
print("Kafka connected!")

# ============================================================
# MQTT CALLBACKS
# ============================================================
def on_connect(client, userdata, flags, rc, properties=None):
    print(f"Connected to EMQX broker!")
    client.subscribe("factory/#", qos=1)
    print(f"Subscribed to factory/# — waiting for messages...\n")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode('utf-8'))
        record = {
            "mqtt_topic": msg.topic,
            "payload": payload,
            "timestamp": time.time()
        }
        producer.send(KAFKA_TOPIC, value=record)
        machine = payload.get('machine_id', '?')
        temp = payload.get('temperature_c', '?')
        fault = payload.get('fault', None)
        fault_str = f" ⚠ FAULT: {fault}" if fault else ""
        print(f"→ Kafka | {machine} | temp: {temp}°C{fault_str}")
    except Exception as e:
        print(f"Error: {e}")

# ============================================================
# CONNECT TO MQTT AND START
# ============================================================
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="factory-bridge")
client.on_connect = on_connect
client.on_message = on_message

print("Connecting to EMQX...")
client.connect(MQTT_BROKER, MQTT_PORT, 60)

print("Bridge running! Press Ctrl+C to stop.\n")
client.loop_forever()
