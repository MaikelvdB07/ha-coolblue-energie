"""Tests: price logic, row parsing, and a full HA setup with a mocked API."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.coolblue_prices.api import gas_price_from_rows, parse_price_rows
from custom_components.coolblue_prices.const import DOMAIN
from custom_components.coolblue_prices.pricing import (
    PriceSettings,
    PriceSlot,
    cheapest_block,
)

TZ = ZoneInfo("Europe/Amsterdam")


# ── pure logic ───────────────────────────────────────────────────────────────


def test_parse_hourly_rows():
    rows = [{"dynamicPrice": 0.20 + i / 100} for i in range(24)]
    slots = parse_price_rows(rows, date(2026, 10, 8))
    assert len(slots) == 24
    assert slots[0].start == datetime(2026, 10, 8, 0, tzinfo=TZ)
    assert slots[13].price == pytest.approx(0.33)
    assert slots[-1].end == datetime(2026, 10, 9, 0, tzinfo=TZ)


def test_parse_rsc_strings_and_unpublished():
    assert parse_price_rows([{"dynamicPrice": "$0"}] * 24, date(2026, 10, 9)) == []
    slots = parse_price_rows([{"dynamicPrice": "$-0.01"}] + [{}] * 23, date(2026, 10, 9))
    assert len(slots) == 1 and slots[0].price == -0.01


def test_parse_dst_days():
    assert len(parse_price_rows([{"dynamicPrice": 0.1}] * 23, date(2026, 3, 29))) == 23
    autumn = parse_price_rows([{"dynamicPrice": 0.1}] * 24, date(2026, 10, 25))
    # Contiguous: every slot ends where the next begins.
    assert all(a.end == b.start for a, b in zip(autumn, autumn[1:]))


def test_parse_quarter_hours():
    slots = parse_price_rows([{"dynamicPrice": 0.1}] * 96, date(2026, 10, 8))
    assert slots[1].start == datetime(2026, 10, 8, 0, 15, tzinfo=TZ)


def test_price_settings():
    all_in = PriceSettings("all_in", purchase_fee=0.02, energy_tax=0.09161, vat=0.21)
    assert all_in.consumption_price(0.30) == 0.30
    market = 0.30 / 1.21 - 0.09161 - 0.02
    assert all_in.feed_in_price(0.30) == pytest.approx(market - 0.02)

    m = PriceSettings("market", purchase_fee=0.02, energy_tax=0.09161, vat=0.21)
    assert m.consumption_price(0.10) == pytest.approx((0.10 + 0.02 + 0.09161) * 1.21)
    assert m.feed_in_price(0.10) == pytest.approx(0.08)


def _slots(prices, start=datetime(2026, 10, 8, 0, tzinfo=TZ)):
    return [
        PriceSlot(start + timedelta(hours=i), start + timedelta(hours=i + 1), p)
        for i, p in enumerate(prices)
    ]


def test_cheapest_block():
    slots = _slots([5, 4, 1, 2, 1, 9, 0.5, 8])
    start, end, avg = cheapest_block(slots, timedelta(hours=3))
    assert start.hour == 2 and end.hour == 5 and avg == pytest.approx(4 / 3)
    # Respect not_before and not_after.
    s, _, _ = cheapest_block(slots, timedelta(hours=1), not_before=slots[3].start)
    assert s.hour == 6
    assert cheapest_block(slots, timedelta(hours=1), not_after=slots[2].start)[0].hour == 1
    assert cheapest_block(slots, timedelta(hours=9)) is None
    # Half-hour block inside hourly data.
    assert cheapest_block(slots, timedelta(minutes=30))[0].hour == 6


def test_gas_price():
    gas = [{"gas": {"usage": 0.5}}, {"gas": {"usage": {"total": 0.5}}}]
    costs = [{"gas": {"cost": {"amount": 0.6}}}, {"gas": {"cost": {"amount": 0.6}}}]
    assert gas_price_from_rows(gas, costs) == pytest.approx(1.2)
    assert gas_price_from_rows([], []) is None


# ── Home Assistant setup ─────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


async def test_setup_and_sensors(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to(datetime(2026, 10, 8, 14, 5, tzinfo=TZ))

    today = [0.30] * 24
    today[3] = today[4] = today[5] = 0.10  # cheap night
    today[15] = today[16] = 0.05  # cheap afternoon: 15:00-17:00
    tomorrow = [0.25] * 24

    async def fake_insights(debtor, location, day, commodity, granularity="HOUR"):
        if commodity == "electricity":
            prices = today if day == date(2026, 10, 8) else tomorrow
            return [{"dynamicPrice": p} for p in prices]
        if commodity == "gas":
            return [{"gas": {"usage": 1.0}}]
        return [{"gas": {"cost": {"amount": 1.3}}}]

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="123_abc",
        data={"email": "a@b.nl", "password": "x", "debtor_id": "123", "location_id": "abc"},
        options={"block_hours": 2, "purchase_fee": 0.02},
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.coolblue_prices.api.CoolblueApi.get_insights",
            new=AsyncMock(side_effect=fake_insights),
        ),
        patch("custom_components.coolblue_prices.api.CoolblueApi.close", new=AsyncMock()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        states = {s.entity_id: s for s in hass.states.async_all()}
        price = next(s for e, s in states.items() if e.startswith("sensor.") and e.endswith("_electricity_price"))
        assert float(price.state) == pytest.approx(0.30)
        assert price.attributes["tomorrow_available"] is True
        assert len(price.attributes["prices_tomorrow"]) == 24

        block = next(s for e, s in states.items() if e.endswith("cheapest_block_start"))
        assert block.attributes["start"].startswith("2026-10-08T15:00")

        gas = next(s for e, s in states.items() if e.endswith("gas_price"))
        assert float(gas.state) == pytest.approx(1.3)

        active = next(s for e, s in states.items() if e.startswith("binary_sensor."))
        assert active.state == "off"

        resp = await hass.services.async_call(
            DOMAIN,
            "find_cheapest_block",
            {"duration": {"hours": 3}},
            blocking=True,
            return_response=True,
        )
        assert resp["found"] and resp["start"].startswith("2026-10-08T14:00")

        # Move into the block: binary sensor turns on at the quarter tick.
        freezer.move_to(datetime(2026, 10, 8, 15, 0, 2, tzinfo=TZ))
        from pytest_homeassistant_custom_component.common import async_fire_time_changed

        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        active = hass.states.get(active.entity_id)
        assert active.state == "on"

        assert await hass.config_entries.async_unload(entry.entry_id)
