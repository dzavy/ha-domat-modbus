"""Sensors: temperature, humidity, schedule state (+ weekly schedule)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfTemperature
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
        [DomatTemperature(coord), DomatHumidity(coord), DomatScheduleState(coord)]
    )


class DomatTemperature(DomatEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "temperature", "Temperature")

    @property
    def native_value(self) -> float:
        return p.to_temp(self.regs[p.REG_ACTUAL_TEMP])


class DomatHumidity(DomatEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "humidity", "Humidity")
        # only enable on types that actually report humidity
        self._attr_entity_registry_enabled_default = bool(coordinator.data[p.REG_ACTUAL_RH])

    @property
    def native_value(self) -> float:
        return self.regs[p.REG_ACTUAL_RH] / 100


class DomatScheduleState(DomatEntity, SensorEntity):
    """Current day/night/off state; the weekly schedule is in the attributes."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [p.MODE_DAY, p.MODE_NIGHT, p.MODE_OFF]
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "schedule", "Schedule")

    @property
    def native_value(self) -> str:
        return self.coordinator.mode

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            day: [p.format_event(m, v) for m, v in events]
            for day, events in self.coordinator.schedule.items()
        }
        attrs["schedule_enabled"] = p.schedule_type(self.regs) == p.SCHEDULE_TYPE_DAY_NIGHT
        return attrs
