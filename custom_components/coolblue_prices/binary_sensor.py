"""Binary sensor: are we inside the cheapest block right now?"""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import CoolblueConfigEntry
from .entity import CoolblueEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CoolblueConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([CheapestBlockActive(entry.runtime_data, "cheapest_block_active")])


class CheapestBlockActive(CoolblueEntity, BinarySensorEntity):
    _attr_icon = "mdi:piggy-bank"

    @property
    def is_on(self) -> bool:
        now = dt_util.now()
        block = self.coordinator.cheapest_block_now(now)
        return bool(block and block[0] <= now < block[1])
