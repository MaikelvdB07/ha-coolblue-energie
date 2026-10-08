"""Data coordinator: fetches today's/tomorrow's prices and yesterday's gas price."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import API_ERRORS, TZ_NL, CoolblueApi, CoolblueAuthError
from .const import (
    CONF_BLOCK_HOURS,
    CONF_DEBTOR_ID,
    CONF_ENERGY_TAX,
    CONF_GAS_PRICE_FALLBACK,
    CONF_LOCATION_ID,
    CONF_PRICE_MODE,
    CONF_PURCHASE_FEE,
    CONF_VAT,
    DEFAULT_BLOCK_HOURS,
    DEFAULT_ENERGY_TAX,
    DEFAULT_GAS_PRICE_FALLBACK,
    DEFAULT_PRICE_MODE,
    DEFAULT_PURCHASE_FEE,
    DEFAULT_VAT,
    DOMAIN,
    TOMORROW_AVAILABLE_FROM_HOUR,
    UPDATE_INTERVAL,
)
from .pricing import PriceSettings, PriceSlot, cheapest_block, slot_at

_LOGGER = logging.getLogger(__name__)


@dataclass
class PriceData:
    """Everything the entities need."""

    today: list[PriceSlot] = field(default_factory=list)
    tomorrow: list[PriceSlot] = field(default_factory=list)
    gas_price: float | None = None
    gas_price_date: date | None = None
    fetched_at: datetime | None = None

    @property
    def all_slots(self) -> list[PriceSlot]:
        return [*self.today, *self.tomorrow]


type CoolblueConfigEntry = ConfigEntry[CoolbluePriceCoordinator]


class CoolbluePriceCoordinator(DataUpdateCoordinator[PriceData]):
    """Polls Coolblue every 30 minutes, but only fetches what is missing."""

    config_entry: CoolblueConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: CoolblueConfigEntry, api: CoolblueApi
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.api = api
        self._debtor = entry.data[CONF_DEBTOR_ID]
        self._location = entry.data[CONF_LOCATION_ID]
        self._cache: dict[date, list[PriceSlot]] = {}
        self._gas: tuple[date, float] | None = None
        self._block: tuple[datetime, datetime, float] | None = None

    # ── settings from the options flow ────────────────────────────────────────

    @property
    def settings(self) -> PriceSettings:
        o = self.config_entry.options
        return PriceSettings(
            price_mode=o.get(CONF_PRICE_MODE, DEFAULT_PRICE_MODE),
            purchase_fee=float(o.get(CONF_PURCHASE_FEE, DEFAULT_PURCHASE_FEE)),
            energy_tax=float(o.get(CONF_ENERGY_TAX, DEFAULT_ENERGY_TAX)),
            vat=float(o.get(CONF_VAT, DEFAULT_VAT)) / 100,
        )

    @property
    def block_duration(self) -> timedelta:
        hours = float(self.config_entry.options.get(CONF_BLOCK_HOURS, DEFAULT_BLOCK_HOURS))
        return timedelta(minutes=round(hours * 60))

    @property
    def gas_price_fallback(self) -> float | None:
        value = float(
            self.config_entry.options.get(CONF_GAS_PRICE_FALLBACK, DEFAULT_GAS_PRICE_FALLBACK)
        )
        return value or None

    # ── derived values ───────────────────────────────────────────────────────

    def consumption_slots(self) -> list[PriceSlot]:
        s = self.settings
        return [
            PriceSlot(x.start, x.end, s.consumption_price(x.price))
            for x in (self.data.all_slots if self.data else [])
        ]

    def feed_in_slots(self) -> list[PriceSlot]:
        s = self.settings
        return [
            PriceSlot(x.start, x.end, s.feed_in_price(x.price))
            for x in (self.data.all_slots if self.data else [])
        ]

    def find_block(
        self, duration: timedelta, now: datetime, until: datetime | None = None
    ) -> tuple[datetime, datetime, float] | None:
        """Cheapest upcoming window, starting no earlier than the current slot."""
        slots = self.consumption_slots()
        current = slot_at(slots, now)
        start_from = current.start if current else now
        return cheapest_block(slots, duration, not_before=start_from, not_after=until)

    def cheapest_block_now(self, now: datetime) -> tuple[datetime, datetime, float] | None:
        """The configured cheapest block; sticky while it is running."""
        if self._block and self._block[0] <= now < self._block[1]:
            return self._block
        self._block = self.find_block(self.block_duration, now)
        return self._block

    # ── fetching ─────────────────────────────────────────────────────────────

    async def _prices_for(self, day: date) -> list[PriceSlot]:
        if day in self._cache:
            return self._cache[day]
        slots = await self.api.get_electricity_prices(self._debtor, self._location, day)
        if slots:
            self._cache[day] = slots
        return slots

    async def _async_update_data(self) -> PriceData:
        now = dt_util.now().astimezone(TZ_NL)
        today = now.date()
        tomorrow = today + timedelta(days=1)
        yesterday = today - timedelta(days=1)

        # Drop days we no longer need.
        for day in list(self._cache):
            if day < today:
                del self._cache[day]

        try:
            today_slots = await self._prices_for(today)
            tomorrow_slots: list[PriceSlot] = []
            if now.hour >= TOMORROW_AVAILABLE_FROM_HOUR:
                tomorrow_slots = await self._prices_for(tomorrow)

            if self._gas is None or self._gas[0] < yesterday:
                gas = await self.api.get_gas_price(self._debtor, self._location, yesterday)
                if gas is not None:
                    self._gas = (yesterday, gas)
        except CoolblueAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except API_ERRORS as err:
            raise UpdateFailed(f"Fout bij ophalen Coolblue-prijzen: {err}") from err

        if not today_slots:
            _LOGGER.warning(
                "Coolblue gaf geen prijzen voor vandaag (%s). Draai probe.py om te "
                "zien wat de API teruggeeft.",
                today,
            )

        return PriceData(
            today=today_slots,
            tomorrow=tomorrow_slots,
            gas_price=self._gas[1] if self._gas else None,
            gas_price_date=self._gas[0] if self._gas else None,
            fetched_at=now,
        )
