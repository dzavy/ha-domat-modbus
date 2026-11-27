"""Relay outputs DO1 / DO2 (the one used for heating is driven by the thermostat)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import protocol as p
from .coordinator import DomatConfigEntry
from .entity import DomatEntity

OUTPUTS = [("do1", "DO1", 0x01), ("do2", "DO2", 0x02)]


async def async_setup_entry(
    hass: HomeAssistant, entry: DomatConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coord = entry.runtime_data
    async_add_entities(
        DomatOutput(coord, key, name, bit)
        for key, name, bit in OUTPUTS
        if bit != coord.heating_bit
    )


class DomatOutput(DomatEntity, SwitchEntity):
    def __init__(self, coordinator, key: str, name: str, bit: int) -> None:
        super().__init__(coordinator, key, name)
        self._bit = bit

    @property
    def is_on(self) -> bool:
        return bool(self.regs[p.REG_RELAY] & self._bit)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_relay_bit(self._bit, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_relay_bit(self._bit, False)
