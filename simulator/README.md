# Factory Simulator

This module runs on a separate edge device (HP laptop) to simulate
3 industrial machines publishing MQTT telemetry.

## Machines Simulated

- **CNC Mill** — temperature, spindle RPM, vibration, tool wear, motor load
- **Conveyor** — belt speed, motor load, running hours, status
- **Hydraulic Press** — pressure, oil temperature, cycle count

## MQTT Topics

- `factory/cnc_mill/telemetry`
- `factory/conveyor/telemetry`
- `factory/hydraulic_press/telemetry`

## Running

Publishes telemetry every 1 second to EMQX broker on port 1883.
