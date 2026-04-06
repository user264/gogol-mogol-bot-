"""Cook handlers: view own stats, feedback."""
from __future__ import annotations

from datetime import date

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from decimal import Decimal

from app.database import async_session
from app.models import User
from app.services import cook_service as cs
from app.services.calc import calc_day
from app.services.reports import fmt_hours
from app.services.pdf_report import cook_payslip_pdf
from app.keyboards.inline import back_menu_kb, cancel_inline_kb
from app.handlers.states import FeedbackFSM
from app.handlers import common as common_mod

router = Router()


def _current_period() -> tuple[date, date]:
    today = date.today()
    if today.day >= 16:
        start = date(today.year, today.month, 16)
    else:
        m = today.month - 1 if today.month > 1 else 12
        y = today.year if today.month > 1 else today.year - 1
        start = date(y, m, 16)
    if start.month == 12:
        end = date(start.year + 1, 1, 15)
    else:
        end = date(start.year, start.month + 1, 15)
    return start, end


async def _get_cook_id(db_user: User, state: FSMContext) -> int | None:
    """Get cook_id from user or from owner's view_as_cook_id."""
    if db_user.cook_id:
        return db_user.cook_id
    if db_user.role == "owner":
        data = await state.get_data()
        return data.get("view_as_cook_id")
    return None


@router.callback_query(F.data == "menu:my_stats")
async def my_stats(cb: CallbackQuery, state: FSMContext, db_user: User | None):
    cook_id = await _get_cook_id(db_user, state) if db_user else None
    if not cook_id:
        await cb.message.edit_text("Повар не выбран.", reply_markup=back_menu_kb())
        return await cb.answer()

    start, end = _current_period()

    async with async_session() as session:
        cook = await session.get(cs.Cook, cook_id)
        if not cook:
            await cb.message.edit_text("Повар не найден.", reply_markup=back_menu_kb())
            return await cb.answer()

        shifts = await cs.get_shifts_for_cook_period(session, cook.id, start, end)
        if not shifts:
            await cb.message.edit_text(
                f"Нет смен за {start:%d.%m} — {end:%d.%m.%Y}.",
                reply_markup=back_menu_kb(),
            )
            return await cb.answer()

        threshold = Decimal(await cs.get_config(session, "revenue_threshold") or "200000")
        bonus_step = Decimal(await cs.get_config(session, "bonus_step") or "6844")

        rate_now = await cs.get_rate_on_date(session, cook.id, date.today())

        total_hours = Decimal("0")
        total_base = Decimal("0")
        total_bonus = Decimal("0")
        day_lines = []

        for s in shifts:
            rate = await cs.get_rate_on_date(session, cook.id, s.shift_date)
            hours = Decimal(str(s.hours_worked))
            base = (hours * rate).quantize(Decimal("0.01"))
            total_hours += hours
            total_base += base

            bonus = Decimal("0")
            pct = 0
            rev_rec = await cs.get_revenue(session, s.shift_date)
            if rev_rec:
                day_shifts = await cs.get_shifts_for_date(session, s.shift_date)
                cook_data = []
                for ds in day_shifts:
                    r = await cs.get_rate_on_date(session, ds.cook_id, ds.shift_date)
                    cook_data.append((ds.cook_id, ds.cook.name, Decimal(str(ds.hours_worked)), r, bool(ds.is_extra)))
                results, _, _, _, day_pct = calc_day(cook_data, Decimal(str(rev_rec.revenue)), threshold, bonus_step)
                pct = day_pct
                for r in results:
                    if r.cook_id == cook.id:
                        bonus = r.bonus
                        break
            total_bonus += bonus

            bonus_str = f"+{bonus:,.0f}" if bonus > 0 else "—"
            day_lines.append(
                f"  {s.shift_date:%d.%m} │ {fmt_hours(hours)} ч │ {base:,.0f} │ {bonus_str}"
            )

        total = total_base + total_bonus

        lines = [
            f"👨‍🍳 {cook.name}",
            f"📅 {start:%d.%m} — {end:%d.%m.%Y}",
            f"💵 Ставка: {rate_now:,.0f} тг/ч",
            "",
            "Дата  │ Часы │ Оклад │ Премия",
            "─" * 30,
        ]
        lines.extend(day_lines)
        lines.append("─" * 30)
        lines.append("")
        lines.append(f"⏱ Часов: {fmt_hours(total_hours)}")
        lines.append(f"💼 Оклад: {total_base:,.0f} тг")
        lines.append(f"🎁 Премия: {total_bonus:,.0f} тг")
        lines.append("")
        lines.append(f"💰 К выплате: {total:,.0f} тг")

    await cb.message.edit_text("\n".join(lines), reply_markup=back_menu_kb())
    await cb.answer()


# --- PDF payslip ---

@router.callback_query(F.data == "menu:my_pdf")
async def my_pdf(cb: CallbackQuery, state: FSMContext, db_user: User | None):
    cook_id = await _get_cook_id(db_user, state) if db_user else None
    if not cook_id:
        await cb.message.edit_text("Повар не выбран.", reply_markup=back_menu_kb())
        return await cb.answer()

    start, end = _current_period()

    async with async_session() as session:
        cook = await session.get(cs.Cook, cook_id)
        if not cook:
            await cb.message.edit_text("Повар не найден.", reply_markup=back_menu_kb())
            return await cb.answer()

        pdf_bytes = await cook_payslip_pdf(session, cook.id, start, end)

    if not pdf_bytes:
        await cb.message.edit_text("Нет данных для отчёта.", reply_markup=back_menu_kb())
        return await cb.answer()

    doc = BufferedInputFile(pdf_bytes, filename=f"payslip_{cook.name}_{start:%d%m}_{end:%d%m%Y}.pdf")
    await cb.message.answer_document(doc, caption=f"📄 Расчётный лист: {cook.name}\n{start:%d.%m} — {end:%d.%m.%Y}")
    await cb.message.edit_text("📄 PDF отправлен!", reply_markup=back_menu_kb())
    await cb.answer()


# --- Feedback to owner ---

@router.callback_query(F.data == "menu:feedback")
async def start_feedback(cb: CallbackQuery, state: FSMContext, db_user: User | None):
    if not db_user:
        return await cb.answer("Нет доступа.", show_alert=True)
    await state.update_data(msg_id=cb.message.message_id, chat_id=cb.message.chat.id)
    await state.set_state(FeedbackFSM.choose_anon)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👤 С именем", callback_data="fb_anon:no"),
            InlineKeyboardButton(text="🕶 Анонимно", callback_data="fb_anon:yes"),
        ],
        [InlineKeyboardButton(text="Отмена", callback_data="cancel_fsm")],
    ])
    await cb.message.edit_text(
        "✉️ Обращение к руководству\n"
        "\n"
        "Привет! Это Герман 👋\n"
        "Когда я создавал эту компанию, я хотел, чтобы она "
        "строилась на честности, справедливости и постоянном "
        "движении вперед 🚀 Сейчас мне важно узнать твое мнение: "
        "как мы справляемся и где мы можем стать лучше?\n"
        "\n"
        "💡 Если у тебя есть идея, предложение или "
        "проблема, которая тебя беспокоит — напиши мне здесь.\n"
        "\n"
        "🤝 Я лично прочту каждое сообщение и обещаю, что ни одно "
        "из них не останется без моего внимания.\n"
        "\n"
        "Как отправить?",
        reply_markup=kb,
    )
    await cb.answer()


@router.callback_query(FeedbackFSM.choose_anon, F.data.startswith("fb_anon:"))
async def pick_anon(cb: CallbackQuery, state: FSMContext):
    is_anon = cb.data == "fb_anon:yes"
    await state.update_data(is_anon=is_anon)
    await state.set_state(FeedbackFSM.enter_text)
    label = "анонимно" if is_anon else "с вашим именем"
    await cb.message.edit_text(
        f"✉️ Напишите сообщение ({label}):",
        reply_markup=cancel_inline_kb(),
    )
    await cb.answer()


@router.message(FeedbackFSM.enter_text)
async def send_feedback(message: Message, state: FSMContext, db_user: User):
    text = message.text.strip()
    if not text:
        return await message.answer("Напишите текст сообщения.")

    data = await state.get_data()
    is_anon = data.get("is_anon", False)

    # Delete user's message
    try:
        await message.delete()
    except Exception:
        pass

    # Find owner(s)
    async with async_session() as session:
        from sqlalchemy import select
        result = await session.execute(select(User).where(User.role == "owner"))
        owners = result.scalars().all()

    # Build message
    if is_anon:
        header = "🕶 Анонимное сообщение от сотрудника:"
    else:
        name = db_user.name or str(db_user.telegram_id)
        header = f"👤 Сообщение от {name}:"

    feedback_text = f"✉️ {header}\n\n{text}"

    # Send to all owners
    sent = False
    if common_mod.bot_instance:
        for owner in owners:
            try:
                await common_mod.bot_instance.send_message(owner.telegram_id, feedback_text)
                sent = True
            except Exception:
                pass

    # Edit original bot message
    bot = common_mod.bot_instance
    if bot and data.get("msg_id"):
        try:
            result_text = "✅ Сообщение отправлено!" if sent else "❌ Не удалось отправить."
            await bot.edit_message_text(
                chat_id=data["chat_id"],
                message_id=data["msg_id"],
                text=result_text,
                reply_markup=back_menu_kb(),
            )
        except Exception:
            pass

    await state.clear()
