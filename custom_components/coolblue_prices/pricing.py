"""Pure price logic (no Home Assistant imports, so it is easy to unit-test)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

PRICE_MODE_ALL_IN = "all_in"
PRICE_MODE_MARKET = "market"


@dataclass(frozen=True)
class PriceSettings:
    """How to turn Coolblue's ``dynamicPrice`` into the prices you pay/receive."""

    price_mode: str = PRICE_MODE_ALL_IN
    """``all_in``: dynamicPrice is already incl. inkoopvergoeding, EB and btw.
    ``market``: dynamicPrice is the bare EPEX price (excl. everything)."""

    purchase_fee: float = 0.0
    """Inkoopvergoeding in EUR/kWh, excl. btw."""

    energy_tax: float = 0.0
    """Energiebelasting in EUR/kWh, excl. btw."""

    vat: float = 0.21

    def market_price(self, dynamic_price: float) -> float:
        """Bare market price (EUR/kWh, excl. btw)."""
        if self.price_mode == PRICE_MODE_MARKET:
            return dynamic_price
        return dynamic_price / (1 + self.vat) - self.energy_tax - self.purchase_fee

    def consumption_price(self, dynamic_price: float) -> float:
        """What you pay per kWh, all-in."""
        if self.price_mode == PRICE_MODE_ALL_IN:
            return dynamic_price
        return (dynamic_price + self.purchase_fee + self.energy_tax) * (1 + self.vat)

    def feed_in_price(self, dynamic_price: float) -> float:
        """What you get per kWh fed back: market price minus inkoopvergoeding."""
        return self.market_price(dynamic_price) - self.purchase_fee


@dataclass(frozen=True)
class PriceSlot:
    """One price interval (an hour, or a quarter when Coolblue provides it)."""

    start: datetime
    end: datetime
    price: float

    def as_dict(self, decimals: int = 5) -> dict:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "price": round(self.price, decimals),
        }


def slot_at(slots: list[PriceSlot], moment: datetime) -> PriceSlot | None:
    """The slot that contains *moment*."""
    for slot in slots:
        if slot.start <= moment < slot.end:
            return slot
    return None


def cheapest_block(
    slots: list[PriceSlot],
    duration: timedelta,
    *,
    not_before: datetime | None = None,
    not_after: datetime | None = None,
) -> tuple[datetime, datetime, float] | None:
    """Cheapest contiguous window of *duration* (time-weighted average price).

    Only windows that start at or after *not_before* and end at or before
    *not_after* are considered. Returns ``(start, end, average_price)``.
    """
    ordered = sorted(slots, key=lambda s: s.start)
    if not_before is not None:
        # A slot already running counts from its start, so "now" still finds it.
        ordered = [s for s in ordered if s.end > not_before]
    if not_after is not None:
        ordered = [s for s in ordered if s.start < not_after]

    best: tuple[datetime, datetime, float] | None = None
    for i, first in enumerate(ordered):
        start = first.start
        if not_before is not None and start < not_before:
            # Skip a slot that has already started; keeps windows actionable.
            continue
        end = start + duration
        if not_after is not None and end > not_after:
            break
        covered = timedelta(0)
        cost = 0.0
        expected_start = start
        for slot in ordered[i:]:
            if slot.start != expected_start:  # gap in the data
                break
            take = min(slot.end, end) - slot.start
            cost += slot.price * take.total_seconds()
            covered += take
            expected_start = slot.end
            if covered >= duration:
                break
        if covered < duration:
            continue
        avg = cost / duration.total_seconds()
        if best is None or avg < best[2]:
            best = (start, end, avg)
    return best


def summary(slots: list[PriceSlot]) -> dict[str, float | None]:
    """Min / max / average of a set of slots."""
    if not slots:
        return {"min": None, "max": None, "average": None}
    prices = [s.price for s in slots]
    return {
        "min": min(prices),
        "max": max(prices),
        "average": sum(prices) / len(prices),
    }
