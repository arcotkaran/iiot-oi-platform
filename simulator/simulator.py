"""
Factory simulator v3: three machines publishing telemetry to MQTT every second.

Normal running is stable (temperatures settle at an operating point, with a slow
day/night ambient swing). On top of that, two independent event lanes:

  FAULT lane      - real problems that keep developing until maintenance fixes them
  TRANSIENT lane  - harmless excursions: a reading climbs for a while, then settles
                    back down on its own (a hard batch of material, a hot afternoon,
                    a heavy load run). Early on they look exactly like real faults.

Ground truth (which event is running, and whether it is real or harmless) goes to
the container log ONLY, never to MQTT, so the fault finder cannot see the answers.
"""
import os
import json
import time
import random
import math
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

# ============================================================
# CONFIGURATION (all overridable from docker-compose / .env)
# ============================================================
BROKER_IP = os.environ.get("MQTT_BROKER", "localhost")
BROKER_PORT = int(os.environ.get("MQTT_PORT", "1883"))

SCENARIOS_ENABLED = os.environ.get("SCENARIOS_ENABLED", "true").lower() == "true"
SCENARIO_SPEED = float(os.environ.get("SCENARIO_SPEED", "1.0"))       # 2 = events play out 2x faster
SCENARIO_GAP_MIN = float(os.environ.get("SCENARIO_GAP_MIN", "40"))    # minutes between real faults
SCENARIO_GAP_MAX = float(os.environ.get("SCENARIO_GAP_MAX", "80"))
TRANSIENTS_ENABLED = os.environ.get("TRANSIENTS_ENABLED", "true").lower() == "true"
TRANSIENT_GAP_MIN = float(os.environ.get("TRANSIENT_GAP_MIN", "30"))  # minutes between harmless excursions
TRANSIENT_GAP_MAX = float(os.environ.get("TRANSIENT_GAP_MAX", "60"))
SCENARIO_FORCE = os.environ.get("SCENARIO_FORCE", "").strip()         # start this event straight away (demos)

# ============================================================
# EVENT CATALOGUE  (durations in minutes at SCENARIO_SPEED=1; each run picks a
# random duration in the range and a random size of 0.7-1.3x, so no two are alike)
# ============================================================
FAULTS = {
    # Worn spindle bearing: vibration creeps up, accelerating, until repaired.
    "cnc_bearing_wear":      {"machine": "cnc_mill",        "minutes": (100, 140), "repair": True},
    # Coolant pump failing: the mill runs hotter and may start tripping on OVERHEAT.
    "cnc_cooling_failure":   {"machine": "cnc_mill",        "minutes": (30, 50),   "repair": True},
    # Jammed belt / failing motor: load and running temperature drift upward.
    "conveyor_motor_strain": {"machine": "conveyor",        "minutes": (70, 110),  "repair": True},
    # Oil cooler fouled: oil temperature climbs and may trip OIL_OVERTEMP.
    "press_cooler_failure":  {"machine": "hydraulic_press", "minutes": (30, 50),   "repair": True},
    # Instrument fault: pressure reading freezes while the press keeps running.
    "press_stuck_sensor":    {"machine": "hydraulic_press", "minutes": (6, 14),    "repair": False},
    # Network / PLC comms loss: one machine goes silent.
    "data_dropout":          {"machine": None,              "minutes": (2, 6),     "repair": False},
}
TRANSIENTS = {
    # Hard material batch / chip build-up: vibration up for a while, then back.
    "cnc_vibration_transient":   {"machine": "cnc_mill",        "minutes": (20, 40)},
    # Coolant briefly low / heavy cut: the mill runs warmer, then settles.
    "cnc_temperature_transient": {"machine": "cnc_mill",        "minutes": (25, 45)},
    # Heavy load run on the belt: motor works harder, then returns to normal.
    "conveyor_load_transient":   {"machine": "conveyor",        "minutes": (15, 35)},
    # Long high-duty run / hot afternoon: oil warms up, then cools back.
    "press_oil_temp_transient":  {"machine": "hydraulic_press", "minutes": (25, 45)},
}
ALL_EVENTS = {**FAULTS, **TRANSIENTS}
MACHINES = ["cnc_mill", "conveyor", "hydraulic_press"]


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"{ts} | {msg}", flush=True)


# ============================================================
# EVENT ENGINE
# ============================================================
class Lane:
    """One stream of events (real faults, or harmless transients)."""

    def __init__(self, kind, catalogue, enabled, gap_min, gap_max):
        self.kind, self.catalogue, self.enabled = kind, catalogue, enabled
        self.gap_min, self.gap_max = gap_min, gap_max
        self.active = None
        self.next_start = None


class ScenarioEngine:
    def __init__(self, enabled=True, speed=1.0, gap_min=40, gap_max=80, force="",
                 transients=True, t_gap_min=30, t_gap_max=60, rng=None):
        self.speed = max(speed, 0.01)
        self.rng = rng or random.Random()
        self.now = 0.0
        self.maintenance = {}   # machine -> time the repair finishes
        self.faults = Lane("fault", FAULTS, enabled, gap_min, gap_max)
        self.transients = Lane("benign", TRANSIENTS, enabled and transients, t_gap_min, t_gap_max)
        self.forced = force if force in ALL_EVENTS else ""
        if force and not self.forced:
            log(f"WARNING: unknown SCENARIO_FORCE '{force}'. Valid: {', '.join(ALL_EVENTS)}")

    # ---------- scheduling ----------
    def _schedule(self, lane, now):
        lane.next_start = now + self.rng.uniform(lane.gap_min, lane.gap_max) * 60 / self.speed

    def _busy_machines(self):
        busy = set(self.maintenance)
        for lane in (self.faults, self.transients):
            if lane.active:
                busy.add(lane.active["machine"])
        return busy

    def _start(self, lane, name, now):
        spec = lane.catalogue[name]
        free = [m for m in MACHINES if m not in self._busy_machines()]
        machine = spec["machine"] or (self.rng.choice(free) if free else None)
        if machine is None or machine not in free:
            self.next_retry(lane, now)     # machine busy: try again shortly
            return
        minutes = self.rng.uniform(*spec["minutes"])
        duration = max(minutes * 60 / self.speed, 20)
        ev = {"name": name, "machine": machine, "start": now, "end": now + duration,
              "size": round(self.rng.uniform(0.7, 1.3), 2), "frozen": None,
              "rise": self.rng.uniform(0.35, 0.5), "hold": self.rng.uniform(0.1, 0.25)}
        lane.active = ev
        log(f"SCENARIO START | kind={lane.kind} | {name} | machine={machine} | "
            f"duration={duration / 60:.1f}min | size={ev['size']} (speed x{self.speed:g})")

    def next_retry(self, lane, now):
        lane.next_start = now + 120 / self.speed

    def tick(self, now):
        self.now = now
        for m, until in list(self.maintenance.items()):
            if now >= until:
                del self.maintenance[m]
                log(f"MAINTENANCE END | machine={m} | back in service")

        for lane in (self.faults, self.transients):
            if not lane.enabled:
                continue
            if lane.next_start is None:
                if self.forced in lane.catalogue:
                    lane.next_start = now + 10     # brief pause so MQTT is connected first
                else:
                    self._schedule(lane, now)

            if lane.active and now >= lane.active["end"]:
                ev = lane.active
                lane.active = None
                if lane.kind == "fault" and lane.catalogue[ev["name"]]["repair"]:
                    repair_s = max(self.rng.uniform(5, 10) * 60 / self.speed, 45)
                    self.maintenance[ev["machine"]] = now + repair_s
                    log(f"SCENARIO END   | kind={lane.kind} | {ev['name']} | machine={ev['machine']} | "
                        f"repaired: maintenance stop {repair_s / 60:.1f}min")
                else:
                    log(f"SCENARIO END   | kind={lane.kind} | {ev['name']} | machine={ev['machine']}")
                self._schedule(lane, now)

            if not lane.active and now >= lane.next_start:
                if self.forced in lane.catalogue:
                    name, self.forced = self.forced, ""
                else:
                    name = self.rng.choice(list(lane.catalogue))
                self._start(lane, name, now)

    # ---------- queries used by the machine models ----------
    def _event(self, name):
        for lane in (self.faults, self.transients):
            if lane.active and lane.active["name"] == name:
                return lane.active
        return None

    def is_active(self, name):
        return self._event(name) is not None

    def progress(self, name):
        ev = self._event(name)
        if not ev:
            return 0.0
        span = ev["end"] - ev["start"]
        return min(1.0, max(0.0, (self.now - ev["start"]) / span)) if span > 0 else 1.0

    def amount(self, name):
        """How strongly an event is affecting its machine right now (0 = not at all)."""
        ev = self._event(name)
        if not ev:
            return 0.0
        p = self.progress(name)
        if name in TRANSIENTS:
            # rise -> hold -> fall back to normal, with smooth corners
            r, h = ev["rise"], ev["hold"]
            if p < r:
                x = p / r
            elif p < r + h:
                x = 1.0
            else:
                x = 1 - (p - r - h) / (1 - r - h)
            x = max(0.0, min(1.0, x))
            return ev["size"] * x * x * (3 - 2 * x)
        if name == "cnc_bearing_wear":
            return ev["size"] * p ** 1.6            # wear accelerates
        if name in ("cnc_cooling_failure", "press_cooler_failure"):
            return ev["size"] * min(1.0, p / 0.15)  # cooling degrades quickly, then stays bad
        return ev["size"] * p

    def in_maintenance(self, machine):
        return machine in self.maintenance

    def silent_machine(self):
        ev = self._event("data_dropout")
        return ev["machine"] if ev else None

    def ambient(self):
        """Slow day/night swing of +-2 C in factory ambient temperature."""
        return 2.0 * math.sin(2 * math.pi * (self.now % 86400) / 86400)

    def describe(self):
        parts = []
        for lane in (self.faults, self.transients):
            if lane.active:
                parts.append(f"{lane.active['name']} {self.progress(lane.active['name']) * 100:.0f}%")
        parts += [f"{m} maintenance" for m in self.maintenance]
        return ", ".join(parts)


# ============================================================
# MACHINE STATE
# ============================================================
def fresh_machines():
    return {
        "cnc_mill": {"temperature": 60.0, "spindle_rpm": 0.0, "vibration": 0.0,
                     "tool_wear": random.uniform(0, 60), "tripped": False, "stop_until": 0.0,
                     "stop_code": None},
        "conveyor": {"temperature": 45.0, "belt_speed": 0.0, "motor_load": 0.0,
                     "running_hours": 142.5},
        "hydraulic_press": {"pressure": 0.0, "cycle_count": 4823, "oil_temp": 50.0,
                            "tripped": False},
    }


machines = fresh_machines()


def approach(value, target, rate, noise):
    """First-order lag toward a target plus a little random wander (like real thermal mass)."""
    return value + (target - value) * rate + random.gauss(0, noise)


# ============================================================
# SIMULATE: update each machine's state
# ============================================================
def update_cnc(state, t, eng):
    now = eng.now
    wear_amt = eng.amount("cnc_bearing_wear")
    maint = eng.in_maintenance("cnc_mill")

    # Tool change: every time the cutter is worn out, a one-minute stop and a fresh tool.
    if not maint and not state["tripped"] and state["tool_wear"] >= 95 and state["stop_until"] <= now:
        state["stop_until"], state["stop_code"], state["tool_wear"] = now + 60, "TOOL_CHANGE", 0.0
    tool_change = state["stop_until"] > now

    running = not (maint or state["tripped"] or tool_change)
    if running:
        state["spindle_rpm"] = 3200 + random.uniform(-50, 50)
        target = (62.0 + eng.ambient() + 12.0 * eng.amount("cnc_temperature_transient")
                  + 33.0 * eng.amount("cnc_cooling_failure") + 4.0 * wear_amt)
        state["temperature"] = approach(state["temperature"], target, 0.004, 0.08)
        vib_base = (2.1 + 0.15 * state["tool_wear"] / 100 + 2.2 * wear_amt
                    + 0.9 * eng.amount("cnc_vibration_transient"))
        state["vibration"] = vib_base + random.uniform(-0.3, 0.3) * (1 + wear_amt)
        state["tool_wear"] = min(100, state["tool_wear"] + 0.01)
    else:
        state["spindle_rpm"] = 0
        state["vibration"] = 0
        state["temperature"] = approach(state["temperature"], 30.0 + eng.ambient(), 0.008, 0.05)

    # Protective shutdown at 85 C; the controller allows a restart once below 55 C.
    if state["temperature"] > 85:
        state["tripped"] = True
    elif state["tripped"] and state["temperature"] < 55:
        state["tripped"] = False

    if maint:
        fault = "MAINTENANCE"
    elif state["tripped"]:
        fault = "OVERHEAT"
    elif tool_change:
        fault = state["stop_code"]
    elif state["tool_wear"] > 90:
        fault = "TOOL_WEAR_HIGH"
    else:
        fault = None
    running = not (maint or state["tripped"] or tool_change)

    return {
        "machine_id": "cnc_mill",
        "timestamp": time.time(),
        "spindle_rpm": round(state["spindle_rpm"], 1),
        "temperature_c": round(state["temperature"] + random.gauss(0, 0.15), 2),
        "vibration_mms": round(max(0.0, state["vibration"]), 3),
        "tool_wear_pct": round(state["tool_wear"], 2),
        "status": "running" if running else "stopped",
        "fault": fault,
    }


def update_conveyor(state, t, eng):
    strain = eng.amount("conveyor_motor_strain")
    maint = eng.in_maintenance("conveyor")
    if not maint:
        base_load = 65 + 20 * strain + 11 * eng.amount("conveyor_load_transient")
        state["belt_speed"] = 12.5 - 1.0 * strain + random.uniform(-0.5, 0.5)
        state["motor_load"] = base_load + random.uniform(-5, 5)
        # Running temperature follows the motor's workload (~45 C at normal load).
        target = 45.0 + 0.6 * (base_load - 65) + 0.5 * eng.ambient()
        state["temperature"] = approach(state["temperature"], target, 0.05, 0.2)
        state["running_hours"] += 1 / 3600
    else:
        state["belt_speed"] = 0
        state["motor_load"] = 0
        state["temperature"] = approach(state["temperature"], 28.0, 0.004, 0.05)

    if maint:
        fault = "MAINTENANCE"
    elif state["running_hours"] > 200:
        fault = "BEARING_SERVICE_DUE"
    else:
        fault = None

    return {
        "machine_id": "conveyor",
        "timestamp": time.time(),
        "belt_speed_mpm": round(state["belt_speed"], 2),
        "motor_load_pct": round(state["motor_load"], 1),
        "temperature_c": round(state["temperature"], 2),
        "running_hours": round(state["running_hours"], 2),
        "status": "stopped" if maint else "running",
        "fault": fault,
    }


def update_press(state, t, eng):
    maint = eng.in_maintenance("hydraulic_press")
    running = not (maint or state["tripped"])
    cycle_phase = math.sin(t * 0.2)
    if running:
        state["pressure"] = max(0, 180 * cycle_phase + random.uniform(-5, 5))
        target = (52.0 + eng.ambient() + 10.0 * eng.amount("press_oil_temp_transient")
                  + 33.0 * eng.amount("press_cooler_failure"))
        state["oil_temp"] = approach(state["oil_temp"], target, 0.003, 0.05)
        if cycle_phase > 0.95:
            state["cycle_count"] += 1
    else:
        state["pressure"] = 0
        state["oil_temp"] = approach(state["oil_temp"], 35.0, 0.006, 0.03)

    # Protective shutdown at 75 C oil; restart allowed once below 58 C.
    if state["oil_temp"] > 75:
        state["tripped"] = True
    elif state["tripped"] and state["oil_temp"] < 58:
        state["tripped"] = False
    running = not (maint or state["tripped"])

    fault = "MAINTENANCE" if maint else ("OIL_OVERTEMP" if state["tripped"] else None)

    # Stuck sensor: the press keeps cycling, but the reported value freezes.
    reported_pressure = state["pressure"]
    ev = eng._event("press_stuck_sensor")
    if ev and running:
        if ev["frozen"] is None:
            ev["frozen"] = round(max(state["pressure"], 20 + random.uniform(0, 140)), 1)
        reported_pressure = ev["frozen"]

    return {
        "machine_id": "hydraulic_press",
        "timestamp": time.time(),
        "pressure_bar": round(reported_pressure, 1),
        "oil_temp_c": round(state["oil_temp"] + random.gauss(0, 0.1), 2),
        "cycle_count": state["cycle_count"],
        "status": "running" if running else "stopped",
        "fault": fault,
    }


# ============================================================
# MQTT + MAIN LOOP
# ============================================================
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        log(f"Connected to EMQX broker at {BROKER_IP}:{BROKER_PORT}")
    else:
        log(f"Connection failed with code {rc}")


def main():
    eng = ScenarioEngine(SCENARIOS_ENABLED, SCENARIO_SPEED, SCENARIO_GAP_MIN, SCENARIO_GAP_MAX,
                         SCENARIO_FORCE, TRANSIENTS_ENABLED, TRANSIENT_GAP_MIN, TRANSIENT_GAP_MAX)
    log(f"Simulator v3 | faults {'ON' if SCENARIOS_ENABLED else 'OFF'} every "
        f"{SCENARIO_GAP_MIN:g}-{SCENARIO_GAP_MAX:g} min | harmless transients "
        f"{'ON' if eng.transients.enabled else 'OFF'} every {TRANSIENT_GAP_MIN:g}-{TRANSIENT_GAP_MAX:g} min"
        f" | speed x{SCENARIO_SPEED:g}" + (f" | forcing '{SCENARIO_FORCE}'" if SCENARIO_FORCE else ""))

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="factory-simulator")
    client.on_connect = on_connect
    client.connect(BROKER_IP, BROKER_PORT, 60)
    client.loop_start()

    t = 0
    try:
        while True:
            t += 1
            eng.tick(time.time())
            readings = [
                update_cnc(machines["cnc_mill"], t, eng),
                update_conveyor(machines["conveyor"], t, eng),
                update_press(machines["hydraulic_press"], t, eng),
            ]
            silent = eng.silent_machine()
            for data in readings:
                if data["machine_id"] == silent:
                    continue   # simulated comms loss: nothing published
                client.publish(f"factory/{data['machine_id']}/telemetry", json.dumps(data), qos=1)

            if t % 5 == 0:
                cnc, conv, press = readings
                line = (f"[t={t}s] CNC: {cnc['temperature_c']}°C vib {cnc['vibration_mms']} | "
                        f"Conveyor: load {conv['motor_load_pct']}% {conv['temperature_c']}°C | "
                        f"Press: {press['pressure_bar']} bar oil {press['oil_temp_c']}°C")
                active = eng.describe()
                if active:
                    line += f" | now: {active}"
                log(line)
                for d in readings:
                    if d["fault"] and d["fault"] != "BEARING_SERVICE_DUE":
                        log(f"  FAULT {d['machine_id']}: {d['fault']}")
            time.sleep(1)
    except KeyboardInterrupt:
        log("Simulator stopped.")
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
