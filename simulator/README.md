# simulator — Edge Device

The simulator is the source of all telemetry in the system. It runs on a
separate HP laptop on the same network as the main data centre — mimicking
how a real industrial edge device would sit on a factory floor and publish
sensor readings over MQTT to a central broker.

## Why a separate machine?

Real IIoT environments are cross-network by design: sensors and PLCs on the
plant floor talk to a central broker over MQTT. Running the simulator on
a dedicated device (rather than localhost) exercises the same network path —
MQTT over WiFi to EMQX on a different host — so the architecture reflects
production reality, not just a development convenience.

## Machines simulated

Three industrial machine types, each publishing on its own MQTT topic:

| Machine | Topic | Key telemetry |
|---------|-------|---------------|
| CNC Mill | `factory/cnc_mill/telemetry` | temperature, spindle RPM, vibration, tool wear, motor load |
| Conveyor | `factory/conveyor/telemetry` | belt speed, motor load, running hours, status |
| Hydraulic Press | `factory/hydraulic_press/telemetry` | pressure, oil temperature, cycle count |

Telemetry is published every second using paho-mqtt at QoS 1, so no
messages are dropped even if the broker briefly loses connection.

## Deployment

The simulator runs as a Supervisor service on the HP laptop (192.168.0.183):

```bash
# Check status
sudo supervisorctl status
# factory_simulator    RUNNING

# Start if stopped
sudo service supervisor start
```

Configuration: `/etc/supervisor/conf.d/simulator.conf`

The simulator connects to the main laptop's EMQX broker at 192.168.0.25:1883
(Windows port-forwarded through to WSL2).
