"""Shared entity base."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_NAME, DOMAIN
from .coordinator import CoolbluePriceCoordinator


class CoolblueEntity(CoordinatorEntity[CoolbluePriceCoordinator]):
    """Base entity; also refreshes its state at every quarter-hour boundary."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CoolbluePriceCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(entry.unique_id))},
            name=DEFAULT_NAME,
            manufacturer="Coolblue",
            model="Dynamisch energiecontract",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._tick, minute=[0, 15, 30, 45], second=1
            )
        )

    @callback
    def _tick(self, _now) -> None:
        self.async_write_ha_state()
