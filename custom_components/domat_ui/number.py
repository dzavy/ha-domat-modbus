"""Day and night setpoints."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import protocol as p
from .coordinator import DomatConfigEntry
from .entity import DomatEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: DomatConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coord = entry.runtime_data
    async_add_entities(
        [
            DomatSetpoint(coord, "day_temperature", "Day temperature", p.REG_DAY_TEMP),
            DomatSetpoint(coord, "night_temperature", "Night temperature", p.REG_NIGHT_TEMP),
        ]
    )


class DomatSetpoint(DomatEntity, NumberEntity):
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_step = 0.5
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, key: str, name: str, register: int) -> None:
        super().__init__(coordinator, key, name)
        self._register = register

    @property
    def native_value(self) -> float:
        return p.to_temp(self.regs[self._register])

    @property
    def native_min_value(self) -> float:
        low, high = p.to_temp(self.regs[p.REG_MIN_TEMP]), p.to_temp(self.regs[p.REG_MAX_TEMP])
        return low if low < high else 5.0

    @property
    def native_max_value(self) -> float:
        low, high = p.to_temp(self.regs[p.REG_MIN_TEMP]), p.to_temp(self.regs[p.REG_MAX_TEMP])
        return high if low < high else 35.0

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_write(self._register, p.from_temp(value))
        # if this setpoint is the active one, apply it to the thermostat right away
        active = p.REG_DAY_TEMP if self.coordinator.mode == p.MODE_DAY else p.REG_NIGHT_TEMP
        if self.coordinator.mode != p.MODE_OFF and active == self._register:
            await self.coordinator.async_write(p.REG_SET_TEMP, p.from_temp(value))
