"""Thermostat entity.

HVAC modes:  off -> day/night "off",  auto -> time schedule,  heat -> manual.
Presets:     comfort (day), eco (night), away (holiday).
Target temperature is the unit's "set temp" (reg 11), the value the knob edits.
On every day/night change the coordinator copies the day or night setpoint into it.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    PRESET_AWAY,
    PRESET_COMFORT,
    PRESET_ECO,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import protocol as p
from .coordinator import DomatConfigEntry
from .entity import DomatEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: DomatConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([DomatClimate(entry.runtime_data)])


class DomatClimate(DomatEntity, ClimateEntity):
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.AUTO]
    _attr_preset_modes = [PRESET_COMFORT, PRESET_ECO, PRESET_AWAY]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_precision = 0.1

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "climate", None)

    @property
    def current_temperature(self) -> float:
        return p.to_temp(self.regs[p.REG_ACTUAL_TEMP])

    @property
    def target_temperature(self) -> float:
        return p.to_temp(self.regs[p.REG_SET_TEMP])

    @property
    def min_temp(self) -> float:
        low, high = p.to_temp(self.regs[p.REG_MIN_TEMP]), p.to_temp(self.regs[p.REG_MAX_TEMP])
        return low if low < high else 5.0

    @property
    def max_temp(self) -> float:
        low, high = p.to_temp(self.regs[p.REG_MIN_TEMP]), p.to_temp(self.regs[p.REG_MAX_TEMP])
        return high if low < high else 35.0

    @property
    def current_humidity(self) -> float | None:
        rh = self.regs[p.REG_ACTUAL_RH]
        return rh / 100 if 0 < rh <= 10000 else None

    @property
    def hvac_mode(self) -> HVACMode:
        dn = p.daynight_bits(self.regs)
        if dn & p.DN_OFF:
            return HVACMode.OFF
        if dn & (p.DN_DAY | p.DN_NIGHT) or dn == 0:
            return HVACMode.HEAT
        return HVACMode.AUTO

    @property
    def preset_mode(self) -> str | None:
        dn = p.daynight_bits(self.regs)
        if dn & p.DN_OFF:
            return None
        if dn & p.DN_HOLIDAY:
            return PRESET_AWAY
        return {p.MODE_DAY: PRESET_COMFORT, p.MODE_NIGHT: PRESET_ECO}.get(self.coordinator.mode)

    @property
    def hvac_action(self) -> HVACAction | None:
        if self.hvac_mode == HVACMode.OFF or self.coordinator.mode == p.MODE_OFF:
            return HVACAction.OFF
        bit = self.coordinator.heating_bit
        if not bit:
            return None
        return HVACAction.HEATING if self.regs[p.REG_RELAY] & bit else HVACAction.IDLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "day_temperature": p.to_temp(self.regs[p.REG_DAY_TEMP]),
            "night_temperature": p.to_temp(self.regs[p.REG_NIGHT_TEMP]),
            "schedule_state": self.coordinator.mode,
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            await self.coordinator.async_write(p.REG_SET_TEMP, p.from_temp(temp))
        if (mode := kwargs.get("hvac_mode")) is not None:
            await self.async_set_hvac_mode(mode)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            bits = p.DN_OFF
        elif hvac_mode == HVACMode.AUTO:
            bits = p.DN_AUTO
        else:
            bits = p.DN_NIGHT if self.preset_mode == PRESET_ECO else p.DN_DAY
        await self.coordinator.async_set_daynight(bits)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        bits = {PRESET_COMFORT: p.DN_DAY, PRESET_ECO: p.DN_NIGHT, PRESET_AWAY: p.DN_HOLIDAY}
        await self.coordinator.async_set_daynight(bits[preset_mode])

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.AUTO)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)
