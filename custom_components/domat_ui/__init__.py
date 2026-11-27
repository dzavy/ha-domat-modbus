"""Domat UIxxx room units over Modbus RTU."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.typing import ConfigType

from . import protocol as p
from .bus import DomatBus
from .const import CONF_HUB, DOMAIN, SERVICE_SET_SCHEDULE
from .coordinator import DomatConfigEntry, DomatCoordinator

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SET_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Required("days"): vol.All(cv.ensure_list, [cv.string]),
        vol.Required("events"): vol.All(cv.ensure_list, [vol.Any(cv.string, dict)]),
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def set_schedule(call: ServiceCall) -> None:
        try:
            days = p.expand_days(call.data["days"])
            events = [p.parse_event(e) for e in call.data["events"]]
            p.encode_day(events)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

        registry = er.async_get(hass)
        coordinators: dict[str, DomatCoordinator] = {}
        for entity_id in call.data[ATTR_ENTITY_ID]:
            entry_id = (ent := registry.async_get(entity_id)) and ent.config_entry_id
            entry = entry_id and hass.config_entries.async_get_entry(entry_id)
            if not entry or entry.domain != DOMAIN or not hasattr(entry, "runtime_data"):
                raise ServiceValidationError(f"{entity_id} is not a Domat UI entity")
            coordinators[entry.entry_id] = entry.runtime_data
        for coordinator in coordinators.values():
            await coordinator.async_set_schedule(days, events)

    hass.services.async_register(DOMAIN, SERVICE_SET_SCHEDULE, set_schedule, SET_SCHEDULE_SCHEMA)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: DomatConfigEntry) -> bool:
    coordinator = DomatCoordinator(hass, entry, DomatBus(hass, entry.data[CONF_HUB]))
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DomatConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: DomatConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
