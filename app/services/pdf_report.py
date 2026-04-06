"""Generate PDF payslip for a cook."""
from __future__ import annotations

import io
import os
from datetime import date
from decimal import Decimal

from fpdf import FPDF
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import cook_service as cs
from app.services.calc import calc_day
from app.services.reports import fmt_hours

# Try common font paths
FONT_PATH = None
for p in [
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
]:
    if os.path.exists(p):
        FONT_PATH = p
        break


async def cook_payslip_pdf(session: AsyncSession, cook_id: int, start: date, end: date) -> bytes:
    cook = await session.get(cs.Cook, cook_id)
    if not cook:
        return b""

    threshold = Decimal(await cs.get_config(session, "revenue_threshold") or "200000")
    bonus_step = Decimal(await cs.get_config(session, "bonus_step") or "6844")
    rate_now = await cs.get_rate_on_date(session, cook.id, date.today())

    shifts = await cs.get_shifts_for_cook_period(session, cook.id, start, end)

    pdf = FPDF()
    pdf.add_page()

    if FONT_PATH:
        pdf.add_font("main", "", FONT_PATH)
        pdf.add_font("main", "B", FONT_PATH)
        font = "main"
    else:
        font = "Helvetica"

    # Header
    pdf.set_font(font, "B", 16)
    pdf.cell(0, 10, "Расчётный лист", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(4)

    pdf.set_font(font, "", 11)
    pdf.cell(0, 7, f"Повар: {cook.name}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, f"Период: {start:%d.%m.%Y} — {end:%d.%m.%Y}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, f"Ставка: {rate_now:,.0f} тг/ч", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Table header
    col_w = [25, 20, 35, 35, 40]
    headers = ["Дата", "Часы", "Оклад", "Премия", "Итого"]
    pdf.set_font(font, "B", 10)
    for i, h in enumerate(headers):
        pdf.cell(col_w[i], 8, h, border=1, align="C")
    pdf.ln()

    # Table rows
    pdf.set_font(font, "", 10)
    total_hours = Decimal("0")
    total_base = Decimal("0")
    total_bonus = Decimal("0")

    for s in shifts:
        s_rate = await cs.get_rate_on_date(session, cook.id, s.shift_date)
        hours = Decimal(str(s.hours_worked))
        base = (hours * s_rate).quantize(Decimal("0.01"))
        total_hours += hours
        total_base += base

        bonus = Decimal("0")
        rev_rec = await cs.get_revenue(session, s.shift_date)
        if rev_rec:
            day_shifts = await cs.get_shifts_for_date(session, s.shift_date)
            cook_data = []
            for ds in day_shifts:
                r = await cs.get_rate_on_date(session, ds.cook_id, ds.shift_date)
                cook_data.append((ds.cook_id, ds.cook.name, Decimal(str(ds.hours_worked)), r, bool(ds.is_extra)))
            results, _, _, _, _ = calc_day(cook_data, Decimal(str(rev_rec.revenue)), threshold, bonus_step)
            for r in results:
                if r.cook_id == cook.id:
                    bonus = r.bonus
                    break
        total_bonus += bonus
        row_total = base + bonus

        row = [
            f"{s.shift_date:%d.%m}",
            fmt_hours(hours),
            f"{base:,.0f}",
            f"{bonus:,.0f}",
            f"{row_total:,.0f}",
        ]
        for i, val in enumerate(row):
            pdf.cell(col_w[i], 7, val, border=1, align="C")
        pdf.ln()

    # Totals row
    total = total_base + total_bonus
    pdf.set_font(font, "B", 10)
    pdf.cell(col_w[0], 8, "Итого", border=1, align="C")
    pdf.cell(col_w[1], 8, fmt_hours(total_hours), border=1, align="C")
    pdf.cell(col_w[2], 8, f"{total_base:,.0f}", border=1, align="C")
    pdf.cell(col_w[3], 8, f"{total_bonus:,.0f}", border=1, align="C")
    pdf.cell(col_w[4], 8, f"{total:,.0f}", border=1, align="C")
    pdf.ln(12)

    # Summary
    pdf.set_font(font, "", 12)
    pdf.cell(0, 8, f"Оклад: {total_base:,.0f} тг", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Премия: {total_bonus:,.0f} тг", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(font, "B", 14)
    pdf.cell(0, 10, f"К выплате: {total:,.0f} тг", new_x="LMARGIN", new_y="NEXT")

    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()
