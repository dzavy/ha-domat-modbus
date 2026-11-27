# Domat UI room units for Home Assistant

Custom integration for Domat UIxxx / UIxxxBL room units (firmware ≥ 200). It adds the
units to a hub of the built-in **Modbus** integration (serial RTU, RTU over TCP or TCP).

## Install

### HACS

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=dzavy&repository=ha-domat-modbus&category=integration)

1. In HACS, open **⋮ → Custom repositories**, add `https://github.com/dzavy/ha-domat-modbus`
   with type **Integration** (or use the button above).
2. Download **Domat UI room units** and restart Home Assistant.

### Manual

Copy `custom_components/domat_ui` to `<config>/custom_components/` and restart.

## Setup

1. Make sure the bus is defined under `modbus:` in `configuration.yaml`. HA only loads a hub
   that has at least one entity of its own; on a bus used only for Domat units, add a
   placeholder sensor:

   ```yaml
   modbus:
     - name: rs485
       type: serial            # or rtuovertcp / tcp with host + port
       method: rtu
       port: /dev/ttyUSB0
       baudrate: 9600
       bytesize: 8
       parity: N
       stopbits: 1
       sensors:
         - name: Domat bus check   # module ID of any unit (reg 1)
           slave: 1
           address: 1
           scan_interval: 3600
   ```
2. Go to **Settings → Devices & services → Add integration → Domat UI room units**.
   Pick the hub and enter the unit's Modbus address. Repeat for each room.
3. Optional: open **Configure** to choose the relay that switches the heating (DO1/DO2), the
   hysteresis and the polling interval.

## Entities (per unit)

| Entity | Registers |
|---|---|
| Climate: current/target temp, off / heat (manual) / auto (schedule), presets comfort / eco / away | 17, 11, 20 |
| Day / night temperature (number) | 12, 13 |
| Temperature, humidity (humidity enabled only if the unit reports it) | 17, 19 |
| Schedule (day / night / off now; weekly programme in attributes) | 8, 101–184 |
| DI1, DI2, Button (binary sensors) | 10 |
| DO1, DO2 (switches; the heating relay is driven by the thermostat instead) | 7 |

Behaviour:
- On each day ↔ night change, the matching setpoint is copied to the target temperature. The
  knob and HA can still change the target until the next change.
- If a heating relay is selected, it is switched on below target − hysteresis and off above
  target + hysteresis, and forced off when the mode is off.
- Nothing is written while someone is turning the knob.

## Weekly schedule

```yaml
action: domat_ui.set_schedule
data:
  entity_id: climate.living_room
  days: [weekdays]             # mon..sun, weekdays, weekend, all
  events: ["06:00 day", "08:00 night", "15:30 day", "22:00 night"]
```

Up to 6 events per day; the other slots are cleared. This is stored permanently in the unit, and
the unit's schedule type is switched to day/night if it isn't already. The schedule runs on the
unit's own clock, which this integration doesn't set.

## Tests

`tests/` runs the integration against a simulated unit on an RTU-over-TCP hub:

```bash
pip install -r requirements_test.txt
pytest
```
