"""Digital inputs DI1, DI2 and the knob push button."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import protocol as p
from .coordinator import DomatConfigEntry
from .entity import DomatEntity

INPUTS = [("di1", "DI1", 0x01), ("di2", "DI2", 0x02), ("button", "Button", 0x04)]


async def async_setup_entry(
    hass: HomeAssistant, entry: DomatConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(
        DomatInput(entry.runtime_data, key, name, bit) for key, name, bit in INPUTS
    )


class DomatInput(DomatEntity, BinarySensorEntity):
    def __init__(self, coordinator, key: str, name: str, bit: int) -> None:
        super().__init__(coordinator, key, name)
        self._bit = bit

    @property
    def is_on(self) -> bool:
        return bool(self.regs[p.REG_INPUTS] & self._bit)
