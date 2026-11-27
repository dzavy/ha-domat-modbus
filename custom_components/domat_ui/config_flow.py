"""Config and options flow: pick a Modbus hub, enter the unit address."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import protocol as p
from .bus import DomatBus, DomatError, available_hubs
from .const import (
    CONF_HEATING_OUTPUT,
    CONF_HUB,
    CONF_HYSTERESIS,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    CONF_UNIT,
    DEFAULT_HYSTERESIS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    OUTPUT_DO1,
    OUTPUT_DO2,
    OUTPUT_NONE,
)

_LOGGER = logging.getLogger(__name__)


class DomatConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        hubs = available_hubs(self.hass)
        if not hubs:
            return self.async_abort(reason="no_hubs")

        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**user_input, CONF_UNIT: int(user_input[CONF_UNIT])}
            await self.async_set_unique_id(f"{data[CONF_HUB]}:{data[CONF_UNIT]}")
            self._abort_if_unique_id_configured()
            try:
                bus = DomatBus(self.hass, data[CONF_HUB])
                module_id = (await bus.read(data[CONF_UNIT], p.REG_MODULE_ID, 1))[0]
            except DomatError as err:
                _LOGGER.debug("Connection test failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                if p.is_domat_module(module_id):
                    return self.async_create_entry(title=data[CONF_NAME], data=data)
                errors["base"] = "not_domat"

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_HUB, default=hubs[0]): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=hubs)
                ),
                vol.Required(CONF_UNIT, default=1): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=247, mode=selector.NumberSelectorMode.BOX)
                ),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return DomatOptionsFlow()


class DomatOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL, default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ): vol.All(vol.Coerce(int), vol.Range(min=5, max=600)),
                vol.Required(
                    CONF_HEATING_OUTPUT, default=opts.get(CONF_HEATING_OUTPUT, OUTPUT_NONE)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[OUTPUT_NONE, OUTPUT_DO1, OUTPUT_DO2],
                        translation_key=CONF_HEATING_OUTPUT,
                    )
                ),
                vol.Required(
                    CONF_HYSTERESIS, default=opts.get(CONF_HYSTERESIS, DEFAULT_HYSTERESIS)
                ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=3.0)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
