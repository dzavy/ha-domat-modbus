"""Thin adapter over a hub of the built-in Modbus integration.

The hub (RTU serial, RTU over TCP or TCP) is defined in configuration.yaml
under `modbus:`; this integration only adds Domat units to it. The hub does
the locking, delays and reconnects; we just look it up by name on every call
so a `modbus.reload` is picked up automatically.
"""

from __future__ import annotations

from homeassistant.components.modbus import get_hub
from homeassistant.components.modbus.const import (
    CALL_TYPE_REGISTER_HOLDING,
    CALL_TYPE_WRITE_REGISTERS,
)
from homeassistant.core import HomeAssistant


class DomatError(Exception):
    """Communication error."""


def available_hubs(hass: HomeAssistant) -> list[str]:
    from homeassistant.components.modbus.modbus import DATA_MODBUS_HUBS

    return sorted(hass.data.get(DATA_MODBUS_HUBS, {}))


class DomatBus:
    def __init__(self, hass: HomeAssistant, hub_name: str) -> None:
        self.hass = hass
        self.hub_name = hub_name

    def _hub(self):
        try:
            return get_hub(self.hass, self.hub_name)
        except KeyError as err:
            raise DomatError(f"Modbus hub '{self.hub_name}' is not configured") from err

    async def read(self, unit: int, address: int, count: int) -> list[int]:
        result = await self._hub().async_pb_call(unit, address, count, CALL_TYPE_REGISTER_HOLDING)
        if result is None or len(result.registers) != count:
            raise DomatError(f"{self.hub_name} unit {unit}: read {address}+{count} failed")
        return list(result.registers)

    async def write(self, unit: int, address: int, values: list[int]) -> None:
        # the device expects 16-bit writes; always use FC16
        result = await self._hub().async_pb_call(unit, address, values, CALL_TYPE_WRITE_REGISTERS)
        if result is None:
            raise DomatError(f"{self.hub_name} unit {unit}: write {address} failed")
