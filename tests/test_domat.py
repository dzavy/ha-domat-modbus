"""End-to-end test of custom_components/domat_ui against a fake RTU-over-TCP room unit."""

import asyncio
from datetime import timedelta
import socket
import struct

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

DOMAIN = "domat_ui"
UNIT = 5


def crc16(data: bytes) -> bytes:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return struct.pack("<H", crc)


class FakeUnit:
    """Minimal Domat UI: FC03 / FC16 over raw RTU frames on TCP."""

    def __init__(self) -> None:
        self.regs = [0] * 1100
        init = {1: 0x0202, 2: 0x0210, 7: 0x0000, 8: 0x01, 10: 0b101, 11: 2300, 12: 2200,
                13: 1800, 17: 2050, 19: 4500, 20: 0x2000, 23: 0x1250, 27: 500, 28: 3000}
        for a, v in init.items():
            self.regs[a] = v
        # monday default programme, rest disabled
        mon = [360, 0, 480, 1, 840, 0, 1320, 1, 360, 0x8000, 360, 0x8000]
        self.regs[101:113] = mon
        for d in range(1, 7):
            self.regs[101 + 12 * d : 113 + 12 * d] = [0, 0x8000] * 6
        self.writes: list[tuple[int, list[int]]] = []
        self.clients = []

    async def handle(self, reader, writer):
        self.clients.append(writer)
        buf = b""
        try:
            while True:
                chunk = await reader.read(256)
                if not chunk:
                    break
                buf += chunk
                while len(buf) >= 8:
                    unit, fc = buf[0], buf[1]
                    size = 8 if fc == 3 else 9 + buf[6] if fc == 16 and len(buf) >= 7 else None
                    if size is None or len(buf) < size:
                        break
                    frame, buf = buf[:size], buf[size:]
                    assert crc16(frame[:-2]) == frame[-2:], "bad CRC from client"
                    if unit != UNIT:
                        continue
                    addr, count = struct.unpack(">HH", frame[2:6])
                    if fc == 3:
                        body = struct.pack(f">BBB{count}H", unit, 3, count * 2, *self.regs[addr:addr + count])
                    else:
                        values = list(struct.unpack(f">{count}H", frame[7:7 + 2 * count]))
                        self.regs[addr:addr + count] = values
                        self.writes.append((addr, values))
                        body = struct.pack(">BBHH", unit, 16, addr, count)
                    writer.write(body + crc16(body))
                    await writer.drain()
        finally:
            writer.close()


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
async def unit(socket_enabled):
    fake = FakeUnit()
    server = await asyncio.start_server(fake.handle, "127.0.0.1", 0)
    fake.port = server.sockets[0].getsockname()[1]
    yield fake
    server.close()
    for w in fake.clients:
        w.close()
    await server.wait_closed()


async def _modbus_hub(hass, unit):
    assert await async_setup_component(hass, "modbus", {"modbus": [
        {"name": "rs485", "type": "rtuovertcp", "host": "127.0.0.1", "port": unit.port,
         "sensors": [{"name": "Domat bus check", "slave": UNIT, "address": 1, "scan_interval": 3600}]}]})
    await hass.async_block_till_done()


async def _setup(hass, unit, options=None):
    await _modbus_hub(hass, unit)
    data = {"name": "Living room", "hub": "rs485", "unit": UNIT}
    entry = MockConfigEntry(domain=DOMAIN, data=data, options=options or {}, unique_id=f"rs485:{UNIT}")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _poll(hass):
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=120))
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_no_hubs(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "no_hubs"


async def test_config_flow(hass, unit):
    await _modbus_hub(hass, unit)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Kitchen", "hub": "rs485", "unit": 7})
    assert result["errors"] == {"base": "cannot_connect"}  # no unit 7 on the bus
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Kitchen", "hub": "rs485", "unit": UNIT})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert hass.states.get("climate.kitchen") is not None
    await hass.config_entries.async_unload(result["result"].entry_id)


async def test_entities_and_controls(hass, unit):
    entry = await _setup(hass, unit)

    st = hass.states.get("climate.living_room")
    assert st.state == "auto"
    assert st.attributes["current_temperature"] == 20.5
    assert st.attributes["temperature"] == 23.0
    assert st.attributes["preset_mode"] == "comfort"
    assert st.attributes["min_temp"] == 5.0 and st.attributes["max_temp"] == 30.0
    assert hass.states.get("sensor.living_room_temperature").state == "20.5"
    assert hass.states.get("sensor.living_room_humidity").state == "45.0"
    assert hass.states.get("binary_sensor.living_room_di1").state == "on"
    assert hass.states.get("binary_sensor.living_room_di2").state == "off"
    assert hass.states.get("binary_sensor.living_room_button").state == "on"
    assert hass.states.get("number.living_room_day_temperature").state == "22.0"
    sched = hass.states.get("sensor.living_room_schedule")
    assert sched.state == "day"
    assert sched.attributes["mon"] == ["06:00 day", "08:00 night", "14:00 day", "22:00 night"]
    assert sched.attributes["tue"] == []
    assert sched.attributes["schedule_enabled"] is False

    # target temperature -> reg 11
    await hass.services.async_call("climate", "set_temperature",
                                   {"entity_id": "climate.living_room", "temperature": 21.5}, blocking=True)
    assert unit.regs[11] == 2150

    # modes -> reg 20 MSB
    await hass.services.async_call("climate", "set_hvac_mode",
                                   {"entity_id": "climate.living_room", "hvac_mode": "off"}, blocking=True)
    assert unit.regs[20] == 0x1000
    await hass.services.async_call("climate", "set_preset_mode",
                                   {"entity_id": "climate.living_room", "preset_mode": "eco"}, blocking=True)
    assert unit.regs[20] == 0x0800
    await _poll(hass)
    st = hass.states.get("climate.living_room")
    assert st.state == "heat" and st.attributes["preset_mode"] == "eco"
    # night manual -> night setpoint copied into set temp
    assert unit.regs[11] == 1800

    # relays keep each other's bits
    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.living_room_do2"}, blocking=True)
    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.living_room_do1"}, blocking=True)
    assert unit.regs[7] == 0b11
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.living_room_do2"}, blocking=True)
    assert unit.regs[7] == 0b01

    # weekly schedule
    await hass.services.async_call(
        DOMAIN, "set_schedule",
        {"entity_id": "climate.living_room", "days": ["weekend"],
         "events": ["22:30 night", "07:30 day", {"time": "23:59", "mode": "off"}]},
        blocking=True,
    )
    assert unit.regs[161:173] == [450, 0, 1350, 1, 1439, 2, 0, 0x8000, 0, 0x8000, 0, 0x8000]
    assert unit.regs[173:185] == unit.regs[161:173]
    assert (unit.regs[23] >> 2) & 3 == 2  # schedule type day/night enabled
    assert unit.regs[3] == 0  # EEPROM write disabled again
    await _poll(hass)
    sched = hass.states.get("sensor.living_room_schedule")
    assert sched.attributes["sat"] == ["07:30 day", "22:30 night", "23:59 off"]
    assert sched.attributes["schedule_enabled"] is True

    with pytest.raises(Exception):
        await hass.services.async_call(DOMAIN, "set_schedule",
                                       {"entity_id": "climate.living_room", "days": ["mon"], "events": ["25:00 day"]},
                                       blocking=True)

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_heating_control(hass, unit):
    entry = await _setup(hass, unit, {"heating_output": "do1", "hysteresis": 0.2, "scan_interval": 15})
    # DO1 is driven by the thermostat -> no switch for it
    assert hass.states.get("switch.living_room_do1") is None
    assert hass.states.get("switch.living_room_do2") is not None
    # 20.5 < 23.0 - 0.2 -> heating on during first poll
    assert unit.regs[7] & 1
    assert hass.states.get("climate.living_room").attributes["hvac_action"] == "heating"

    unit.regs[17] = 2330  # 23.3 > 23.2 -> off
    await _poll(hass)
    assert not unit.regs[7] & 1
    assert hass.states.get("climate.living_room").attributes["hvac_action"] == "idle"

    unit.regs[17] = 2290  # inside the band -> stays off
    await _poll(hass)
    assert not unit.regs[7] & 1

    # schedule goes to night: night setpoint 18.0 copied to set temp
    unit.regs[8] = 0x02
    await _poll(hass)
    assert unit.regs[11] == 1800
    assert hass.states.get("climate.living_room").attributes["preset_mode"] == "eco"

    # off -> relay forced off
    unit.regs[17] = 1500
    await _poll(hass)
    assert unit.regs[7] & 1
    unit.regs[20] = 0x1000
    await _poll(hass)
    assert not unit.regs[7] & 1
    assert hass.states.get("climate.living_room").state == "off"

    # user is turning the knob -> no writes
    unit.regs[20] = 0x2000
    unit.regs[3] = 0x1000
    n = len(unit.writes)
    await _poll(hass)
    assert len(unit.writes) == n

    assert await hass.config_entries.async_unload(entry.entry_id)
