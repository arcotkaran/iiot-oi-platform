import os
import paho.mqtt.client as mqtt
import json
import time
import random
import math

# ============================================================
# CONFIGURATION — Main laptop's IP address
# ============================================================
BROKER_IP = os.environ.get("MQTT_BROKER", "localhost")
BROKER_PORT = 1883

# ============================================================
# MACHINE STATE
# Each machine has a current state that evolves over time
# like a real machine would
# ============================================================
machines = {
    "cnc_mill": {
        "temperature": 25.0,      # starts at room temp
        "spindle_rpm": 0.0,       # starts stopped
        "vibration": 0.0,         # mm/s
        "tool_wear": 0.0,         # percent 0-100
        "running": True,
        "fault": None
    },
    "conveyor": {
        "temperature": 25.0,
        "belt_speed": 0.0,        # m/min
        "motor_load": 0.0,        # percent
        "running_hours": 142.5,   # starts mid-life
        "running": True,
        "fault": None
    },
    "hydraulic_press": {
        "temperature": 25.0,
        "pressure": 0.0,          # bar
        "cycle_count": 4823,      # starts mid-life
        "oil_temp": 35.0,         # oil starts slightly warm
        "running": True,
        "fault": None
    }
}

# ============================================================
# SIMULATE — Update each machine's state realistically
# ============================================================
def update_cnc(state, t):
    # Temperature rises when running, cools when stopped
    if state["running"]:
        state["spindle_rpm"] = 3200 + random.uniform(-50, 50)
        state["temperature"] += random.uniform(0.1, 0.3)
        state["vibration"] = 2.1 + random.uniform(-0.3, 0.3)
        state["tool_wear"] = min(100, state["tool_wear"] + 0.01)
    else:
        state["spindle_rpm"] = 0
        state["temperature"] = max(25, state["temperature"] - 0.5)
        state["vibration"] = 0

    # Overheat fault if temperature exceeds 85°C
    if state["temperature"] > 85:
        state["fault"] = "OVERHEAT"
        state["running"] = False
    elif state["tool_wear"] > 90:
        state["fault"] = "TOOL_WEAR_HIGH"
    else:
        state["fault"] = None
        # Randomly restart if stopped and cooled down
        if not state["running"] and state["temperature"] < 40:
            state["running"] = True

    return {
        "machine_id": "cnc_mill",
        "timestamp": time.time(),
        "spindle_rpm": round(state["spindle_rpm"], 1),
        "temperature_c": round(state["temperature"], 2),
        "vibration_mms": round(state["vibration"], 3),
        "tool_wear_pct": round(state["tool_wear"], 2),
        "status": "running" if state["running"] else "stopped",
        "fault": state["fault"]
    }

def update_conveyor(state, t):
    if state["running"]:
        state["belt_speed"] = 12.5 + random.uniform(-0.5, 0.5)
        state["motor_load"] = 65 + random.uniform(-5, 5)
        # Drift toward operating temperature (~45°C) with realistic noise.
        # Motors warm up, then reach thermal equilibrium with their
        # environment — they don't heat forever.
        target_temp = 45.0
        drift = (target_temp - state["temperature"]) * 0.05
        state["temperature"] += drift + random.uniform(-0.3, 0.3)
        state["running_hours"] += 1/3600  # add one second worth of hours
    else:
        state["belt_speed"] = 0
        state["motor_load"] = 0
        state["temperature"] = max(25, state["temperature"] - 0.2)

    # Bearing fault if running hours exceed threshold
    if state["running_hours"] > 200:
        state["fault"] = "BEARING_SERVICE_DUE"
    else:
        state["fault"] = None

    return {
        "machine_id": "conveyor",
        "timestamp": time.time(),
        "belt_speed_mpm": round(state["belt_speed"], 2),
        "motor_load_pct": round(state["motor_load"], 1),
        "temperature_c": round(state["temperature"], 2),
        "running_hours": round(state["running_hours"], 2),
        "status": "running" if state["running"] else "stopped",
        "fault": state["fault"]
    }

def update_press(state, t):
    # Press cycles — pressure builds then releases
    cycle_phase = math.sin(t * 0.2)  # slow sine wave = press cycle
    if state["running"]:
        state["pressure"] = max(0, 180 * cycle_phase + random.uniform(-5, 5))
        state["oil_temp"] += random.uniform(0.05, 0.15)
        if cycle_phase > 0.95:  # count a cycle at peak pressure
            state["cycle_count"] += 1
    else:
        state["pressure"] = 0
        state["oil_temp"] = max(35, state["oil_temp"] - 0.3)

    # Oil overtemp fault
    if state["oil_temp"] > 75:
        state["fault"] = "OIL_OVERTEMP"
        state["running"] = False
    else:
        state["fault"] = None
        if not state["running"] and state["oil_temp"] < 50:
            state["running"] = True

    return {
        "machine_id": "hydraulic_press",
        "timestamp": time.time(),
        "pressure_bar": round(state["pressure"], 1),
        "oil_temp_c": round(state["oil_temp"], 2),
        "cycle_count": state["cycle_count"],
        "status": "running" if state["running"] else "stopped",
        "fault": state["fault"]
    }

# ============================================================
# MQTT CONNECTION
# ============================================================
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"Connected to EMQX broker at {BROKER_IP}:{BROKER_PORT}")
        print("Publishing machine telemetry... (Ctrl+C to stop)\n")
    else:
        print(f"Connection failed with code {rc}")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="factory-simulator")
client.on_connect = on_connect
client.connect(BROKER_IP, BROKER_PORT, 60)
client.loop_start()

# ============================================================
# MAIN LOOP — publish every second forever
# ============================================================
t = 0
try:
    while True:
        t += 1

        # Update and publish each machine
        cnc_data = update_cnc(machines["cnc_mill"], t)
        conveyor_data = update_conveyor(machines["conveyor"], t)
        press_data = update_press(machines["hydraulic_press"], t)

        for data in [cnc_data, conveyor_data, press_data]:
            topic = f"factory/{data['machine_id']}/telemetry"
            payload = json.dumps(data)
            client.publish(topic, payload, qos=1)

        # Print a summary every 5 seconds so you can see it working
        if t % 5 == 0:
            print(f"[t={t}s] CNC: {cnc_data['temperature_c']}°C | "
                  f"Conveyor: {conveyor_data['belt_speed_mpm']} m/min | "
                  f"Press: {press_data['pressure_bar']} bar")
            if cnc_data['fault']:
                print(f"  ⚠ CNC FAULT: {cnc_data['fault']}")
            if conveyor_data['fault']:
                print(f"  ⚠ CONVEYOR FAULT: {conveyor_data['fault']}")
            if press_data['fault']:
                print(f"  ⚠ PRESS FAULT: {press_data['fault']}")

        time.sleep(1)

except KeyboardInterrupt:
    print("\nSimulator stopped.")
    client.loop_stop()
    client.disconnect()
