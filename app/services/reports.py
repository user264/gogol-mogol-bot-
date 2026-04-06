"""Report generation: daily, monthly, CSV."""
from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.calc import calc_day, CookDayResult
from app.services import cook_service as cs


def fmt_hours(h) -> str:
    """Format hours: show '8' instead of '8.00', but keep '7.5'."""
    f = float(h)
    return str(int(f)) if f == int(f) else str(round(f, 2)).rstrip("0").rstrip(".")


def text_bar(value: Decimal, max_value: Decimal, width: int = 10) -> str:
    """Render a text bar chart segment."""
    if max_value == 0:
        return "\u2591" * width
    filled = int(float(value / max_value) * width)
    return "\u2588" * filled + "\u2591" * (width - filled)


def period_label(start: date, end: date) -> str:
    return f"{start:%d.%m.%Y} — {end:%d.%m.%Y}"


async def _day_calc(session: AsyncSession, d: date, threshold: Decimal, bonus_step: Decimal):
    """Build cook_data for a day and run calc_day."""
    shifts = await cs.get_shifts_for_date(session, d)
    if not shifts:
        return [], Decimal("0"), threshold, bonus_step, 0, shifts

    cook_data = []
    for s in shifts:
        rate = await cs.get_rate_on_date(session, s.cook_id, d)
        cook_data.append((s.cook_id, s.cook.name, Decimal(str(s.hours_worked)), rate, bool(s.is_extra)))

    revenue_rec = await cs.get_revenue(session, d)
    daily_revenue = Decimal(str(revenue_rec.revenue)) if revenue_rec else Decimal("0")

    results, coeff, adj_thr, adj_step, percent = calc_day(cook_data, daily_revenue, threshold, bonus_step)
    return results, coeff, adj_thr, adj_step, percent, shifts


async def daily_report(session: AsyncSession, d: date) -> str:
    threshold = Decimal(await cs.get_config(session, "revenue_threshold") or "200000")
    bonus_step = Decimal(await cs.get_config(session, "bonus_step") or "6844")

    shifts = await cs.get_shifts_for_date(session, d)
    if not shifts:
        return f"Нет данных о сменах за {d:%d.%m.%Y}"

    revenue_rec = await cs.get_revenue(session, d)
    daily_revenue = Decimal(str(revenue_rec.revenue)) if revenue_rec else Decimal("0")
    source_label = "ручной ввод" if (revenue_rec and revenue_rec.source == "manual") else "Poster"

    cook_data = []
    for s in shifts:
        rate = await cs.get_rate_on_date(session, s.cook_id, d)
        cook_data.append((s.cook_id, s.cook.name, Decimal(str(s.hours_worked)), rate, bool(s.is_extra)))

    results, coeff, adj_thr, adj_step, percent = calc_day(cook_data, daily_revenue, threshold, bonus_step)
    total_bonus = sum(r.bonus for r in results)
    total_all = sum(r.total for r in results)

    extra_cooks = [s for s in shifts if s.is_extra]

    no_revenue = not revenue_rec or daily_revenue == 0

    lines = [
        f"\U0001f4ca Итог смены — {d:%d %B %Y}",
        "",
        f"Выручка дня: {daily_revenue:,.0f} тг (источник: {source_label})",
    ]
    if no_revenue:
        lines.append("⚠️ Выручка не внесена! Премия не рассчитана.")
    if extra_cooks:
        lines.append(f"Доп. поваров: {len(extra_cooks)} | Коэфф: {coeff}")
        lines.append(f"Порог: {threshold:,.0f} → {adj_thr:,.0f} тг | Шаг: {bonus_step:,.0f} → {adj_step:,.0f} тг")
    else:
        lines.append(f"Порог: {adj_thr:,.0f} тг | Шаг: {adj_step:,.0f} тг")
    lines.append(f"Премия: {percent}% от оклада" + (" ✅" if percent > 0 else " ❌"))
    lines.append("")

    for r in results:
        extra_mark = " (доп)" if any(s.cook_id == r.cook_id and s.is_extra for s in shifts) else ""
        lines.append(
            f"\U0001f468\u200d\U0001f373 {r.cook_name}{extra_mark} — {fmt_hours(r.hours)} ч | "
            f"Оклад: {r.base_pay:,.0f} | Премия {percent}%: {r.bonus:,.0f} | Итого: {r.total:,.0f} тг"
        )
    lines.append("")
    lines.append(f"Суммарно: оклад {sum(r.base_pay for r in results):,.0f} + премия {total_bonus:,.0f} = {total_all:,.0f} тг")
    return "\n".join(lines)


async def _cook_totals(session, cook, start, end, threshold, bonus_step):
    """Calculate totals for a single cook over a period."""
    shifts = await cs.get_shifts_for_cook_period(session, cook.id, start, end)
    total_hours = Decimal("0")
    total_base = Decimal("0")
    total_bonus = Decimal("0")
    day_lines = []

    for s in shifts:
        rate = await cs.get_rate_on_date(session, cook.id, s.shift_date)
        hours = Decimal(str(s.hours_worked))
        base = hours * rate
        total_hours += hours
        total_base += base

        bonus = Decimal("0")
        revenue_rec = await cs.get_revenue(session, s.shift_date)
        if revenue_rec:
            results, _, _, _, _ = await _day_calc_cached(session, s.shift_date, threshold, bonus_step)
            for r in results:
                if r.cook_id == cook.id:
                    bonus = r.bonus
                    break
        total_bonus += bonus
        day_lines.append((s.shift_date, hours, base, bonus))

    return shifts, total_hours, total_base, total_bonus, day_lines


async def _day_calc_cached(session, d, threshold, bonus_step):
    """Run full day calc with extra cook logic."""
    day_shifts = await cs.get_shifts_for_date(session, d)
    revenue_rec = await cs.get_revenue(session, d)
    daily_revenue = Decimal(str(revenue_rec.revenue)) if revenue_rec else Decimal("0")

    cook_data = []
    for s in day_shifts:
        rate = await cs.get_rate_on_date(session, s.cook_id, s.shift_date)
        cook_data.append((s.cook_id, s.cook.name, Decimal(str(s.hours_worked)), rate, bool(s.is_extra)))

    return calc_day(cook_data, daily_revenue, threshold, bonus_step)


async def period_report(session: AsyncSession, start: date, end: date) -> str:
    cooks = await cs.get_active_cooks(session)
    threshold = Decimal(await cs.get_config(session, "revenue_threshold") or "200000")
    bonus_step = Decimal(await cs.get_config(session, "bonus_step") or "6844")

    lines = [f"\U0001f4c5 Отчёт за {period_label(start, end)}", ""]
    grand_total = Decimal("0")

    # First pass: collect totals per cook
    cook_results = []
    for cook in cooks:
        shifts, total_hours, total_base, total_bonus, _ = await _cook_totals(
            session, cook, start, end, threshold, bonus_step
        )
        if not shifts:
            continue
        total = total_base + total_bonus
        grand_total += total
        cook_results.append((cook, len(shifts), total_hours, total_base, total_bonus, total))

    # Determine max total for bar chart scaling
    max_total = max((t for _, _, _, _, _, t in cook_results), default=Decimal("0"))

    for cook, days, total_hours, total_base, total_bonus, total in cook_results:
        pct = int(float(total / grand_total) * 100) if grand_total > 0 else 0
        lines.append(
            f"\U0001f468\u200d\U0001f373 {cook.name}: "
            f"{days} дн, {fmt_hours(total_hours)} ч | "
            f"Оклад: {total_base:,.0f} | Премия: {total_bonus:,.0f} | Итого: {total:,.0f} тг"
        )
        lines.append(f"   {text_bar(total, max_total)} {pct}%")

    lines.append("")
    lines.append(f"Всего: {grand_total:,.0f} тг")
    return "\n".join(lines)


async def cook_period_report(session: AsyncSession, cook_id: int, start: date, end: date) -> str:
    cook = await session.get(cs.Cook, cook_id)
    if not cook:
        return "Повар не найден."

    threshold = Decimal(await cs.get_config(session, "revenue_threshold") or "200000")
    bonus_step = Decimal(await cs.get_config(session, "bonus_step") or "6844")

    shifts, total_hours, total_base, total_bonus, day_lines = await _cook_totals(
        session, cook, start, end, threshold, bonus_step
    )
    if not shifts:
        return f"Нет смен у {cook.name} за {period_label(start, end)}."

    lines = [f"\U0001f468\u200d\U0001f373 {cook.name} — {period_label(start, end)}", ""]
    for shift_date, hours, base, bonus in day_lines:
        lines.append(f"  {shift_date:%d.%m} — {fmt_hours(hours)} ч | {base:,.0f} + {bonus:,.0f} = {base + bonus:,.0f} тг")

    total = total_base + total_bonus
    lines.append("")
    lines.append(f"Итого: {len(shifts)} дн, {fmt_hours(total_hours)} ч")
    lines.append(f"Оклад: {total_base:,.0f} | Премия: {total_bonus:,.0f}")
    lines.append(f"К выплате: {total:,.0f} тг")
    return "\n".join(lines)


async def period_csv(session: AsyncSession, start: date, end: date) -> bytes:
    cooks = await cs.get_active_cooks(session)
    threshold = Decimal(await cs.get_config(session, "revenue_threshold") or "200000")
    bonus_step = Decimal(await cs.get_config(session, "bonus_step") or "6844")

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Повар", "Дата", "Часы", "Доп", "Ставка", "Оклад", "Премия", "Итого"])

    for cook in cooks:
        shifts = await cs.get_shifts_for_cook_period(session, cook.id, start, end)
        for s in shifts:
            rate = await cs.get_rate_on_date(session, cook.id, s.shift_date)
            hours = Decimal(str(s.hours_worked))
            base = hours * rate

            bonus = Decimal("0")
            revenue_rec = await cs.get_revenue(session, s.shift_date)
            if revenue_rec:
                results, _, _, _, _ = await _day_calc_cached(session, s.shift_date, threshold, bonus_step)
                for r in results:
                    if r.cook_id == cook.id:
                        bonus = r.bonus
                        break

            writer.writerow([
                cook.name,
                s.shift_date.isoformat(),
                str(hours),
                "да" if s.is_extra else "",
                str(rate),
                str(base.quantize(Decimal("0.01"))),
                str(bonus),
                str((base + bonus).quantize(Decimal("0.01"))),
            ])

    return buf.getvalue().encode("utf-8-sig")
