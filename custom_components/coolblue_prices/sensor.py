"""Sensors for Coolblue Energie Prijzen."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import CURRENCY_EURO, UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import CoolblueConfigEntry, CoolbluePriceCoordinator
from .entity import CoolblueEntity
from .pricing import PriceSlot, slot_at, summary

EUR_KWH = f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}"
EUR_M3 = f"{CURRENCY_EURO}/{UnitOfVolume.CUBIC_METERS}"


def _now() -> datetime:
    return dt_util.now()


def _today(slots: list[PriceSlot], now: datetime) -> list[PriceSlot]:
    return [s for s in slots if s.start.date() == now.date()]


def _tomorrow(slots: list[PriceSlot], now: datetime) -> list[PriceSlot]:
    return [s for s in slots if s.start.date() > now.date()]


def _price_attrs(slots: list[PriceSlot], now: datetime) -> dict[str, Any]:
    today = _today(slots, now)
    tomorrow = _tomorrow(slots, now)
    stats_today = summary(today)
    stats_tomorrow = summary(tomorrow)
    return {
        "prices_today": [s.as_dict() for s in today],
        "prices_tomorrow": [s.as_dict() for s in tomorrow],
        "tomorrow_available": bool(tomorrow),
        "min_today": _r(stats_today["min"]),
        "max_today": _r(stats_today["max"]),
        "average_today": _r(stats_today["average"]),
        "min_tomorrow": _r(stats_tomorrow["min"]),
        "max_tomorrow": _r(stats_tomorrow["max"]),
        "average_tomorrow": _r(stats_tomorrow["average"]),
    }


def _r(value: float | None, digits: int = 5) -> float | None:
    return None if value is None else round(value, digits)


def _current(slots: list[PriceSlot]) -> float | None:
    slot = slot_at(slots, _now())
    return _r(slot.price) if slot else None


def _next(slots: list[PriceSlot]) -> float | None:
    current = slot_at(slots, _now())
    if current is None:
        return None
    nxt = slot_at(slots, current.end)
    return _r(nxt.price) if nxt else None


def _stat(key: str) -> Callable[[CoolbluePriceCoordinator], float | None]:
    def fn(c: CoolbluePriceCoordinator) -> float | None:
        return _r(summary(_today(c.consumption_slots(), _now()))[key])

    return fn


@dataclass(frozen=True, kw_only=True)
class CoolblueSensorDescription(SensorEntityDescription):
    value_fn: Callable[[CoolbluePriceCoordinator], Any]
    attrs_fn: Callable[[CoolbluePriceCoordinator], dict[str, Any]] | None = None


def _block_attrs(c: CoolbluePriceCoordinator) -> dict[str, Any]:
    block = c.cheapest_block_now(_now())
    hours = c.block_duration.total_seconds() / 3600
    if not block:
        return {"duration_hours": hours}
    return {
        "start": block[0].isoformat(),
        "end": block[1].isoformat(),
        "average_price": _r(block[2]),
        "duration_hours": hours,
    }


def _block_start(c: CoolbluePriceCoordinator) -> datetime | None:
    block = c.cheapest_block_now(_now())
    return block[0] if block else None


def _gas_attrs(c: CoolbluePriceCoordinator) -> dict[str, Any]:
    d = c.data
    if d and d.gas_price is not None:
        return {"source": "coolblue", "price_date": d.gas_price_date.isoformat()}
    if c.gas_price_fallback is not None:
        return {"source": "fallback_option"}
    return {"source": None}


def _gas_value(c: CoolbluePriceCoordinator) -> float | None:
    if c.data and c.data.gas_price is not None:
        return _r(c.data.gas_price)
    return c.gas_price_fallback


SENSORS: tuple[CoolblueSensorDescription, ...] = (
    CoolblueSensorDescription(
        key="current_price",
        native_unit_of_measurement=EUR_KWH,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        icon="mdi:flash",
        value_fn=lambda c: _current(c.consumption_slots()),
        attrs_fn=lambda c: _price_attrs(c.consumption_slots(), _now()),
    ),
    CoolblueSensorDescription(
        key="next_price",
        native_unit_of_measurement=EUR_KWH,
        suggested_display_precision=3,
        icon="mdi:flash-outline",
        value_fn=lambda c: _next(c.consumption_slots()),
    ),
    CoolblueSensorDescription(
        key="feed_in_price",
        native_unit_of_measurement=EUR_KWH,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        icon="mdi:solar-power",
        value_fn=lambda c: _current(c.feed_in_slots()),
        attrs_fn=lambda c: _price_attrs(c.feed_in_slots(), _now()),
    ),
    CoolblueSensorDescription(
        key="min_price_today",
        native_unit_of_measurement=EUR_KWH,
        suggested_display_precision=3,
        icon="mdi:arrow-down-bold",
        value_fn=_stat("min"),
    ),
    CoolblueSensorDescription(
        key="max_price_today",
        native_unit_of_measurement=EUR_KWH,
        suggested_display_precision=3,
        icon="mdi:arrow-up-bold",
        value_fn=_stat("max"),
    ),
    CoolblueSensorDescription(
        key="average_price_today",
        native_unit_of_measurement=EUR_KWH,
        suggested_display_precision=3,
        icon="mdi:approximately-equal",
        value_fn=_stat("average"),
    ),
    CoolblueSensorDescription(
        key="cheapest_block_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-start",
        value_fn=_block_start,
        attrs_fn=_block_attrs,
    ),
    CoolblueSensorDescription(
        key="gas_price",
        native_unit_of_measurement=EUR_M3,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        icon="mdi:fire",
        value_fn=_gas_value,
        attrs_fn=_gas_attrs,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CoolblueConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(CoolblueSensor(coordinator, d) for d in SENSORS)


class CoolblueSensor(CoolblueEntity, SensorEntity):
    entity_description: CoolblueSensorDescription

    def __init__(
        self, coordinator: CoolbluePriceCoordinator, description: CoolblueSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.attrs_fn
        return fn(self.coordinator) if fn else None
