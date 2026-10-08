"""Client for the (undocumented) Coolblue Energie portal API.

Login and the ``/api/insights`` endpoint follow the work in
barisdemirdelen/homeassistant-coolblue-energy (MIT). Every hourly row that
endpoint returns carries a ``dynamicPrice`` field (EUR/kWh); that is the price
source for this integration.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any, Self
from zoneinfo import ZoneInfo

import aiohttp

from .auth import AuthService, CoolblueAuthError  # noqa: F401  (re-exported)
from .pricing import PriceSlot

_LOGGER = logging.getLogger(__name__)

TZ_NL = ZoneInfo("Europe/Amsterdam")
ENERGY_URL = "https://www.coolblue.nl/nl/mijn-coolblue-account/energie/energieverbruik"
INSIGHTS_URL = "https://www.coolblue.nl/api/insights"

API_ERRORS: tuple[type[Exception], ...] = (
    aiohttp.ClientError,
    TimeoutError,
    RuntimeError,
    ValueError,
)


def _to_float(value: Any) -> float | None:
    """Numbers may arrive as None, number, or a Next.js ``'$-0'``-style string."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return float(value.replace("$", "").strip())
        except ValueError:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def local_hours(day: date) -> list[datetime]:
    """Every wall-clock hour that exists on *day* in Amsterdam, as aware datetimes.

    23 hours on the spring-forward day; on the autumn day the portal folds the
    repeated 02:00 into one row, so we also return 24 (02:00 once).
    """
    hours = []
    for hour in range(24):
        local = datetime(day.year, day.month, day.day, hour, tzinfo=TZ_NL)
        if local.astimezone(UTC).astimezone(TZ_NL).hour == hour:
            hours.append(local)
    return hours


def parse_price_rows(rows: list[dict[str, Any]], day: date) -> list[PriceSlot]:
    """Turn ``/api/insights`` rows into price slots.

    The portal labels row *i* as hour ``i-1`` (off by one), so row position is
    the only reliable hour. Rows without a price are skipped. When the portal
    returns 4x as many rows as hours, they are treated as quarter-hours.
    """
    hours = local_hours(day)
    if not rows:
        return []
    if len(rows) >= len(hours) * 4 - 4:
        step = timedelta(minutes=15)
        starts = [h + step * q for h in hours for q in range(4)]
    else:
        step = timedelta(hours=1)
        starts = hours
    if len(rows) > len(starts):
        raise ValueError(f"Expected at most {len(starts)} rows for {day}, got {len(rows)}")

    next_midnight = datetime.combine(day + timedelta(days=1), datetime.min.time(), TZ_NL)
    # Each slot ends where the next begins; this also absorbs the folded
    # autumn-DST hour instead of leaving a gap.
    ends = [*starts[1:], next_midnight]

    slots: list[PriceSlot] = []
    for row, start, end in zip(rows, starts, ends, strict=False):
        price = _to_float(row.get("dynamicPrice"))
        if price is None:
            continue
        slots.append(PriceSlot(start=start, end=end, price=price))

    # A day where every price is exactly 0 means "not published yet".
    if slots and all(s.price == 0 for s in slots):
        return []
    return slots


def gas_price_from_rows(
    gas_rows: list[dict[str, Any]], cost_rows: list[dict[str, Any]]
) -> float | None:
    """Gas price for a day: an explicit gas price if present, else cost / usage."""
    for row in gas_rows:
        for key in ("gasPrice", "dynamicGasPrice"):
            price = _to_float(row.get(key))
            if price:
                return price
        gas = row.get("gas") or {}
        price = _to_float(gas.get("price")) if isinstance(gas, dict) else None
        if price:
            return price

    usage = 0.0
    for row in gas_rows:
        gas = row.get("gas") or {}
        u = gas.get("usage") if isinstance(gas, dict) else None
        if isinstance(u, dict):
            u = u.get("total")
        usage += _to_float(u) or 0.0
    cost = 0.0
    for row in cost_rows:
        gas = row.get("gas") or {}
        c = gas.get("cost") if isinstance(gas, dict) else None
        if isinstance(c, dict):
            c = c.get("amount")
        cost += _to_float(c) or 0.0
    if usage > 0.05 and cost > 0:
        return cost / usage
    return None


class CoolblueApi:
    """Async client: login, account ids, and price data."""

    def __init__(self, email: str, password: str) -> None:
        self._auth = AuthService(email, password, ENERGY_URL)
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        await self._auth.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # ── account ──────────────────────────────────────────────────────────────

    async def get_energy_ids(self) -> tuple[str, str]:
        """Return ``(debtor_number, location_uuid)`` from the energy page."""
        session = await self._auth.get_session()
        async with session.get(ENERGY_URL) as r:
            r.raise_for_status()
            html = await r.text()

        chunks = re.findall(r'self\.__next_f\.push\(\[1,\s*"((?:[^"\\]|\\.)*)"]\)', html)
        rsc = "\n".join(json.loads(f'"{c}"') for c in chunks)
        debtor = re.search(r'"debtorNumber"\s*:\s*"(\d+)"', rsc)
        location = re.search(r'"locationId"\s*:\s*"([0-9a-f]{8}-[0-9a-f-]{27})"', rsc)
        if debtor and location:
            return debtor.group(1), location.group(1)
        raise RuntimeError(
            "Kon debtorNumber/locationId niet vinden op de energiepagina "
            f"({len(chunks)} RSC-chunks, {len(html)} tekens)."
        )

    # ── raw insights call ────────────────────────────────────────────────────

    async def get_insights(
        self,
        debtor: str,
        location: str,
        day: date,
        commodity: str,
        granularity: str = "HOUR",
    ) -> list[dict[str, Any]]:
        """Raw ``/api/insights`` rows for *day*. Re-logs in once on 401/403."""
        day_start_utc = datetime(day.year, day.month, day.day, tzinfo=TZ_NL).astimezone(UTC)
        params = {
            "granularity": granularity,
            "from": day_start_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "year": str(day.year),
            "month": str(day.month),
            "day": str(day.day),
            "locationId": location,
            "debtorNumber": debtor,
            "commodity": commodity,
            "hasInsightV2": "false",
        }
        async with self._lock:
            for attempt in range(2):
                session = await self._auth.get_session()
                async with session.get(
                    INSIGHTS_URL, params=params, headers={"Accept": "application/json"}
                ) as r:
                    if r.status in (401, 403) and attempt == 0:
                        _LOGGER.debug("Sessie verlopen (%s), opnieuw inloggen", r.status)
                        await self._auth.authenticate()
                        continue
                    if r.status == 404:
                        return []
                    r.raise_for_status()
                    data = json.loads(await r.text())
                    if not isinstance(data, list):
                        raise ValueError(f"Onverwacht antwoord van /api/insights: {str(data)[:200]}")
                    return data
        return []

    # ── prices ───────────────────────────────────────────────────────────────

    async def get_electricity_prices(
        self, debtor: str, location: str, day: date
    ) -> list[PriceSlot]:
        rows = await self.get_insights(debtor, location, day, "electricity")
        return parse_price_rows(rows, day)

    async def get_gas_price(self, debtor: str, location: str, day: date) -> float | None:
        gas_rows = await self.get_insights(debtor, location, day, "gas")
        cost_rows = await self.get_insights(debtor, location, day, "costs")
        return gas_price_from_rows(gas_rows, cost_rows)
