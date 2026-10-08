"""Coolblue Energie Prijzen — dynamic energy prices from your Coolblue account."""

from __future__ import annotations

from datetime import timedelta

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .api import CoolblueApi
from .const import DOMAIN, SERVICE_CHEAPEST_BLOCK, SERVICE_GET_PRICES
from .coordinator import CoolblueConfigEntry, CoolbluePriceCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

ATTR_ENTRY = "config_entry_id"
ATTR_DURATION = "duration"
ATTR_END_BEFORE = "end_before"
ATTR_KIND = "kind"

_GET_PRICES_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY): cv.string,
        vol.Optional(ATTR_KIND, default="consumption"): vol.In(["consumption", "feed_in"]),
    }
)
_BLOCK_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY): cv.string,
        vol.Required(ATTR_DURATION): cv.time_period,
        vol.Optional(ATTR_END_BEFORE): cv.datetime,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_PRICES,
        _get_prices,
        schema=_GET_PRICES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CHEAPEST_BLOCK,
        _find_block,
        schema=_BLOCK_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: CoolblueConfigEntry) -> bool:
    api = CoolblueApi(entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD])
    entry.async_on_unload(api.close)

    coordinator = CoolbluePriceCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    entry.async_on_unload(entry.add_update_listener(_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CoolblueConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _options_updated(hass: HomeAssistant, entry: CoolblueConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _coordinator(call: ServiceCall) -> CoolbluePriceCoordinator:
    entries = [
        e
        for e in call.hass.config_entries.async_entries(DOMAIN)
        if e.state is ConfigEntryState.LOADED
    ]
    wanted = call.data.get(ATTR_ENTRY)
    if wanted:
        entries = [e for e in entries if e.entry_id == wanted]
    if not entries:
        raise ServiceValidationError("Geen geladen Coolblue Energie-integratie gevonden")
    return entries[0].runtime_data


async def _get_prices(call: ServiceCall) -> ServiceResponse:
    c = _coordinator(call)
    slots = c.feed_in_slots() if call.data[ATTR_KIND] == "feed_in" else c.consumption_slots()
    return {"prices": [s.as_dict() for s in slots]}


async def _find_block(call: ServiceCall) -> ServiceResponse:
    c = _coordinator(call)
    duration: timedelta = call.data[ATTR_DURATION]
    until = call.data.get(ATTR_END_BEFORE)
    if until is not None and until.tzinfo is None:
        until = until.replace(tzinfo=dt_util.get_default_time_zone())
    block = c.find_block(duration, dt_util.now(), until)
    if block is None:
        return {"found": False}
    return {
        "found": True,
        "start": block[0].isoformat(),
        "end": block[1].isoformat(),
        "average_price": round(block[2], 5),
    }
