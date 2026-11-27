"""Polling and thermostat logic for one Domat room unit."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import protocol as p
from .bus import DomatBus, DomatError
from .const import (
    CONF_HEATING_OUTPUT,
    CONF_HYSTERESIS,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    CONF_UNIT,
    DEFAULT_HYSTERESIS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    OUTPUT_DO1,
    OUTPUT_DO2,
    SCHEDULE_REFRESH_POLLS,
)

_LOGGER = logging.getLogger(__name__)

type DomatConfigEntry = ConfigEntry[DomatCoordinator]


class DomatCoordinator(DataUpdateCoordinator[dict[int, int]]):
    """Reads registers 1..28 every poll, the schedule now and then."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, bus: DomatBus) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.data[CONF_NAME]}",
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.bus = bus
        self.unit: int = int(entry.data[CONF_UNIT])
        self.schedule: dict[str, list[tuple[int, int]]] = {}
        self.hysteresis: float = entry.options.get(CONF_HYSTERESIS, DEFAULT_HYSTERESIS)
        output = entry.options.get(CONF_HEATING_OUTPUT)
        self.heating_bit: int = {OUTPUT_DO1: 0x01, OUTPUT_DO2: 0x02}.get(output, 0)
        self._polls = 0
        self._last_mode: str | None = None

    # ------------------------------------------------------------------ io
    async def _async_update_data(self) -> dict[int, int]:
        try:
            raw = await self.bus.read(self.unit, p.POLL_START, p.POLL_COUNT)
            if not self.schedule or self._polls % SCHEDULE_REFRESH_POLLS == 0:
                await self._async_read_schedule()
        except DomatError as err:
            raise UpdateFailed(str(err)) from err
        self._polls += 1
        regs = {p.POLL_START + i: v for i, v in enumerate(raw)}
        try:
            await self._async_run_logic(regs)
        except DomatError as err:
            _LOGGER.warning("%s: control write failed: %s", self.name, err)
        return regs

    async def _async_read_schedule(self) -> None:
        raw = await self.bus.read(self.unit, p.REG_SCHEDULE, 42)
        raw += await self.bus.read(self.unit, p.REG_SCHEDULE + 42, 42)
        self.schedule = p.decode_schedule(raw)

    async def async_write(self, address: int, value: int) -> None:
        """Write one register, update local state, refresh soon."""
        try:
            await self.bus.write(self.unit, address, [value])
        except DomatError as err:
            raise HomeAssistantError(str(err)) from err
        if self.data is not None:
            self.data[address] = value
            self.async_update_listeners()
        await self.async_request_refresh()

    async def async_set_daynight(self, bits: int) -> None:
        await self.async_write(p.REG_MODE, p.mode_register_value(self.data, bits))

    async def async_set_relay_bit(self, bit: int, on: bool) -> None:
        current = self.data[p.REG_RELAY]
        await self.async_write(p.REG_RELAY, current | bit if on else current & ~bit & 0xFFFF)

    async def async_set_schedule(self, days: list[str], events: list[tuple[int, int]]) -> None:
        """Write the same events to the given days; persisted to EEPROM."""
        values = p.encode_day(events)
        await self.bus.write(self.unit, p.REG_STATUS, [p.STATUS_EEPROM_WRITE])
        try:
            if p.schedule_type(self.data) != p.SCHEDULE_TYPE_DAY_NIGHT:
                _LOGGER.info("%s: switching time schedule type to day/night", self.name)
                await self.bus.write(
                    self.unit, p.REG_SETTINGS, [p.settings_with_daynight_schedule(self.data)]
                )
            for day in days:
                await self.bus.write(
                    self.unit, p.REG_SCHEDULE + 12 * p.DAYS.index(day), values
                )
        finally:
            await self.bus.write(self.unit, p.REG_STATUS, [0])
        await self._async_read_schedule()
        await self.async_request_refresh()

    # --------------------------------------------------------------- logic
    async def _async_run_logic(self, regs: dict[int, int]) -> None:
        if regs[p.REG_STATUS] & p.STATUS_EDIT_MODE:
            return  # user is turning the knob, device ignores writes anyway

        mode = p.effective_mode(regs)

        # day <-> night transition: load the matching setpoint into "set temp"
        if self._last_mode is not None and mode != self._last_mode and mode != p.MODE_OFF:
            source = p.REG_DAY_TEMP if mode == p.MODE_DAY else p.REG_NIGHT_TEMP
            if regs[source] != regs[p.REG_SET_TEMP]:
                await self.bus.write(self.unit, p.REG_SET_TEMP, [regs[source]])
                regs[p.REG_SET_TEMP] = regs[source]
        self._last_mode = mode

        if not self.heating_bit:
            return
        temp = p.to_temp(regs[p.REG_ACTUAL_TEMP])
        target = p.to_temp(regs[p.REG_SET_TEMP])
        is_on = bool(regs[p.REG_RELAY] & self.heating_bit)
        if mode == p.MODE_OFF:
            want = False
        elif temp < target - self.hysteresis:
            want = True
        elif temp > target + self.hysteresis:
            want = False
        else:
            want = is_on
        if want != is_on:
            relay = regs[p.REG_RELAY]
            relay = relay | self.heating_bit if want else relay & ~self.heating_bit & 0xFFFF
            await self.bus.write(self.unit, p.REG_RELAY, [relay])
            regs[p.REG_RELAY] = relay

    # ---------------------------------------------------------------- info
    @property
    def device_info(self) -> DeviceInfo:
        regs = self.data or {}
        entry = self.config_entry
        return DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            name=entry.data[CONF_NAME],
            manufacturer="Domat Control System",
            model=p.module_name(regs.get(p.REG_MODULE_ID, 0)),
            sw_version=f"{regs.get(p.REG_FIRMWARE, 0):X}",
        )

    @property
    def mode(self) -> str:
        return p.effective_mode(self.data)
