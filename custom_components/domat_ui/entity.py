"""Base entity."""

from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import DomatCoordinator


class DomatEntity(CoordinatorEntity[DomatCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: DomatCoordinator, key: str, name: str | None) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_{key}"
        self._attr_name = name
        self._attr_device_info = coordinator.device_info

    @property
    def regs(self) -> dict[int, int]:
        return self.coordinator.data
