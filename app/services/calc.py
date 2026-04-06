"""Payroll & bonus calculation logic."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

EXTRA_BASE_HOURS = Decimal("12")
EXTRA_FACTOR = Decimal("0.33")
BASE_PERCENT = 10


@dataclass
class CookDayResult:
    cook_id: int
    cook_name: str
    hours: Decimal
    hourly_rate: Decimal
    base_pay: Decimal
    bonus: Decimal
    bonus_percent: int
    total: Decimal


def calc_extra_coeff(extra_hours: dict[int, Decimal]) -> Decimal:
    """extra_coeff = (sum_extra_hours / 12) × 0.33"""
    total_extra = sum(extra_hours.values())
    if total_extra == 0:
        return Decimal("0")
    return (total_extra / EXTRA_BASE_HOURS * EXTRA_FACTOR).quantize(Decimal("0.0001"))


def calc_bonus_percent(daily_revenue: Decimal, threshold: Decimal, step: Decimal) -> int:
    """
    steps = floor((revenue - threshold) / step)
    percent = 10 + steps
    If revenue < threshold → 0.
    """
    if step == 0 or daily_revenue < threshold:
        return 0
    steps = int((daily_revenue - threshold) / step)
    return BASE_PERCENT + steps


def calc_day(
    cook_data: list[tuple[int, str, Decimal, Decimal, bool]],  # (cook_id, name, hours, hourly_rate, is_extra)
    daily_revenue: Decimal,
    threshold: Decimal,
    step: Decimal,
) -> tuple[list[CookDayResult], Decimal, Decimal, Decimal, int]:
    """Returns (results, extra_coeff, adjusted_threshold, adjusted_step, percent)."""
    extra_hours = {cid: hours for cid, _, hours, _, is_extra in cook_data if is_extra}
    coeff = calc_extra_coeff(extra_hours)

    adj_threshold = (threshold * (1 + coeff)).quantize(Decimal("0.01"))
    adj_step = (step * (1 + coeff)).quantize(Decimal("0.01"))

    percent = calc_bonus_percent(daily_revenue, adj_threshold, adj_step)

    results = []
    for cook_id, name, hours, rate, _ in cook_data:
        base = (hours * rate).quantize(Decimal("0.01"))
        bonus = (base * percent / 100).quantize(Decimal("0.01")) if percent > 0 else Decimal("0")
        results.append(CookDayResult(
            cook_id=cook_id,
            cook_name=name,
            hours=hours,
            hourly_rate=rate,
            base_pay=base,
            bonus=bonus,
            bonus_percent=percent,
            total=(base + bonus).quantize(Decimal("0.01")),
        ))
    return results, coeff, adj_threshold, adj_step, percent
