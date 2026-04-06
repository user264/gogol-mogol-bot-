"""Sous-chef handlers: enter hours, edit hours, today's timesheet, revenue, shift report."""
from __future__ import annotations

from datetime import date, timedelta

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from app.database import async_session
from app.models import User, Role
from app.handlers.states import AddShiftFSM, EditShiftFSM, SetRevenueFSM
from app.keyboards.inline import (
    cook_list_kb, date_pick_kb, confirm_kb, with_cancel,
    cancel_inline_kb, hours_kb, back_menu_kb,
)
from app.services import cook_service as cs
from app.services.reports import daily_report, fmt_hours
from app.handlers import common as common_mod

router = Router()


def _is_sous_chef_or_owner(user: User | None) -> bool:
    return user is not None and user.role in ("sous_chef", "owner")


# --- Add shift (regular & extra share the same flow) ---

async def _start_shift_flow_cb(cb: CallbackQuery, state: FSMContext, db_user: User | None, is_extra: bool):
    if not _is_sous_chef_or_owner(db_user):
        return await cb.answer("Нет доступа.", show_alert=True)
    async with async_session() as session:
        cooks = await cs.get_active_cooks(session)
    if not cooks:
        await cb.message.edit_text("Нет активных поваров.", reply_markup=back_menu_kb())
        return await cb.answer()
    await state.update_data(is_extra=is_extra)
    await state.set_state(AddShiftFSM.choose_cook)
    label = "доп. смену" if is_extra else "часы"
    await cb.message.edit_text(
        f"👨\u200d🍳 Вносим {label}. Выберите повара:",
        reply_markup=with_cancel(cook_list_kb(cooks, "addshift")),
    )
    await state.update_data(msg_id=cb.message.message_id, chat_id=cb.message.chat.id)
    await cb.answer()


@router.callback_query(F.data == "menu:add_shift")
async def start_add_shift(cb: CallbackQuery, state: FSMContext, db_user: User | None):
    await _start_shift_flow_cb(cb, state, db_user, is_extra=False)


@router.callback_query(F.data == "menu:add_extra")
async def start_add_extra_shift(cb: CallbackQuery, state: FSMContext, db_user: User | None):
    await _start_shift_flow_cb(cb, state, db_user, is_extra=True)


@router.callback_query(AddShiftFSM.choose_cook, F.data.startswith("addshift:"))
async def pick_cook(cb: CallbackQuery, state: FSMContext):
    cook_id = int(cb.data.split(":")[1])
    async with async_session() as session:
        cook = await session.get(cs.Cook, cook_id)
        cook_name = cook.name if cook else "?"
    await state.update_data(cook_id=cook_id, cook_name=cook_name)
    await state.set_state(AddShiftFSM.choose_date)
    await cb.message.edit_text(
        f"📅 {cook_name}. Выберите дату:",
        reply_markup=with_cancel(date_pick_kb()),
    )
    await cb.answer()


@router.callback_query(AddShiftFSM.choose_date, F.data.startswith("date:"))
async def pick_date(cb: CallbackQuery, state: FSMContext):
    d = cb.data.split(":")[1]
    data = await state.get_data()
    cook_name = data.get("cook_name", "?")
    dt = date.fromisoformat(d)
    await state.update_data(shift_date=d)
    await state.set_state(AddShiftFSM.choose_hours)
    await cb.message.edit_text(
        f"⏰ {cook_name}, {dt:%d.%m}. Часы:",
        reply_markup=hours_kb(),
    )
    await cb.answer()


@router.callback_query(AddShiftFSM.choose_hours, F.data.startswith("hours:"))
async def pick_hours(cb: CallbackQuery, state: FSMContext, db_user: User):
    choice = cb.data.split(":")[1]
    if choice == "custom":
        await state.set_state(AddShiftFSM.enter_hours)
        await cb.message.edit_text("Введите часы числом:", reply_markup=cancel_inline_kb())
        await cb.answer()
        return

    hours = float(choice)
    await _save_shift(cb, state, db_user, hours)


async def _save_shift(cb: CallbackQuery, state: FSMContext, db_user: User, hours: float):
    """Save shift and edit the message to show result."""
    data = await state.get_data()
    async with async_session() as session:
        try:
            await cs.add_shift(
                session,
                cook_id=data["cook_id"],
                shift_date=date.fromisoformat(data["shift_date"]),
                hours=hours,
                entered_by=db_user.id,
                is_extra=data.get("is_extra", False),
            )
            extra_label = " (доп)" if data.get("is_extra") else ""
            cook_name = data.get("cook_name", "?")
            dt = date.fromisoformat(data["shift_date"])
            await cb.message.edit_text(
                f"✅ {cook_name}, {dt:%d.%m}, {fmt_hours(hours)} ч{extra_label} — записано!",
                reply_markup=back_menu_kb(),
            )
            # Notify cook
            cook = await session.get(cs.Cook, data["cook_id"])
            if cook and cook.telegram_id and common_mod.bot_instance:
                # Don't notify if the cook is the one entering
                if cook.telegram_id != cb.from_user.id:
                    try:
                        await common_mod.bot_instance.send_message(
                            cook.telegram_id,
                            f"📝 Вам записана смена: {fmt_hours(hours)} ч, {dt:%d.%m.%Y}{extra_label}",
                        )
                    except Exception:
                        pass
        except ValueError:
            await cb.message.edit_text(
                "Смена за эту дату уже существует. Используйте «✏️ Редактировать».",
                reply_markup=back_menu_kb(),
            )
    await state.clear()
    await cb.answer()


@router.message(AddShiftFSM.enter_hours)
async def enter_hours(message: Message, state: FSMContext, db_user: User):
    try:
        hours = float(message.text.replace(",", "."))
        if hours <= 0 or hours > 24:
            raise ValueError
    except (ValueError, TypeError):
        return await message.answer("Введите число от 0.5 до 24.")

    data = await state.get_data()

    # Delete user's text message
    try:
        await message.delete()
    except Exception:
        pass

    # Edit original message to show result
    async with async_session() as session:
        try:
            await cs.add_shift(
                session,
                cook_id=data["cook_id"],
                shift_date=date.fromisoformat(data["shift_date"]),
                hours=hours,
                entered_by=db_user.id,
                is_extra=data.get("is_extra", False),
            )
            extra_label = " (доп)" if data.get("is_extra") else ""
            cook_name = data.get("cook_name", "?")
            dt = date.fromisoformat(data["shift_date"])
            await common_mod.bot_instance.edit_message_text(
                chat_id=data["chat_id"],
                message_id=data["msg_id"],
                text=f"✅ {cook_name}, {dt:%d.%m}, {fmt_hours(hours)} ч{extra_label} — записано!",
                reply_markup=back_menu_kb(),
            )
        except ValueError:
            await common_mod.bot_instance.edit_message_text(
                chat_id=data["chat_id"],
                message_id=data["msg_id"],
                text="Смена за эту дату уже существует. Используйте «✏️ Редактировать».",
                reply_markup=back_menu_kb(),
            )
    await state.clear()


# --- Edit shift ---

@router.callback_query(F.data == "menu:edit_shift")
async def start_edit_shift(cb: CallbackQuery, state: FSMContext, db_user: User | None):
    if not _is_sous_chef_or_owner(db_user):
        return await cb.answer("Нет доступа.", show_alert=True)
    async with async_session() as session:
        cooks = await cs.get_active_cooks(session)
    if not cooks:
        await cb.message.edit_text("Нет активных поваров.", reply_markup=back_menu_kb())
        return await cb.answer()
    await state.set_state(EditShiftFSM.choose_cook)
    await cb.message.edit_text(
        "👨\u200d🍳 Выберите повара:",
        reply_markup=with_cancel(cook_list_kb(cooks, "editshift")),
    )
    await state.update_data(msg_id=cb.message.message_id, chat_id=cb.message.chat.id)
    await cb.answer()


@router.callback_query(EditShiftFSM.choose_cook, F.data.startswith("editshift:"))
async def edit_pick_cook(cb: CallbackQuery, state: FSMContext):
    cook_id = int(cb.data.split(":")[1])
    async with async_session() as session:
        cook = await session.get(cs.Cook, cook_id)
        cook_name = cook.name if cook else "?"
    await state.update_data(cook_id=cook_id, cook_name=cook_name)
    await state.set_state(EditShiftFSM.choose_date)
    await cb.message.edit_text(
        f"📅 {cook_name}. Выберите дату:",
        reply_markup=with_cancel(date_pick_kb()),
    )
    await cb.answer()


@router.callback_query(EditShiftFSM.choose_date, F.data.startswith("date:"))
async def edit_pick_date(cb: CallbackQuery, state: FSMContext):
    d = cb.data.split(":")[1]
    data = await state.get_data()
    cook_name = data.get("cook_name", "?")
    async with async_session() as session:
        shift = await cs.get_shift_by_cook_date(session, data["cook_id"], date.fromisoformat(d))
    if not shift:
        await cb.message.edit_text("Смена за эту дату не найдена.", reply_markup=back_menu_kb())
        await state.clear()
        return await cb.answer()

    await state.update_data(shift_id=shift.id, old_hours=float(shift.hours_worked), shift_date=d)
    await state.set_state(EditShiftFSM.choose_hours)
    dt = date.fromisoformat(d)
    await cb.message.edit_text(
        f"⏰ {cook_name}, {dt:%d.%m}. Текущее: {fmt_hours(float(shift.hours_worked))} ч.\nНовые часы:",
        reply_markup=hours_kb(),
    )
    await cb.answer()


@router.callback_query(EditShiftFSM.choose_hours, F.data.startswith("hours:"))
async def edit_pick_hours(cb: CallbackQuery, state: FSMContext):
    choice = cb.data.split(":")[1]
    if choice == "custom":
        await state.set_state(EditShiftFSM.enter_hours)
        await cb.message.edit_text("Введите новое количество часов числом:", reply_markup=cancel_inline_kb())
        await cb.answer()
        return

    hours = float(choice)
    await state.update_data(new_hours=hours)
    data = await state.get_data()
    cook_name = data.get("cook_name", "?")
    await state.set_state(EditShiftFSM.enter_reason)
    await cb.message.edit_text(
        f"📝 {cook_name}: {fmt_hours(data['old_hours'])} → {fmt_hours(hours)} ч.\n"
        "Укажите причину изменения (минимум 10 символов):",
        reply_markup=cancel_inline_kb(),
    )
    await cb.answer()


@router.message(EditShiftFSM.enter_hours)
async def edit_enter_hours(message: Message, state: FSMContext):
    try:
        hours = float(message.text.replace(",", "."))
        if hours <= 0 or hours > 24:
            raise ValueError
    except (ValueError, TypeError):
        return await message.answer("Введите число от 0.5 до 24.")

    # Delete user's text message
    try:
        await message.delete()
    except Exception:
        pass

    await state.update_data(new_hours=hours)
    data = await state.get_data()
    cook_name = data.get("cook_name", "?")
    await state.set_state(EditShiftFSM.enter_reason)
    await common_mod.bot_instance.edit_message_text(
        chat_id=data["chat_id"],
        message_id=data["msg_id"],
        text=(
            f"📝 {cook_name}: {fmt_hours(data['old_hours'])} → {fmt_hours(hours)} ч.\n"
            "Укажите причину изменения (минимум 10 символов):"
        ),
        reply_markup=cancel_inline_kb(),
    )


@router.message(EditShiftFSM.enter_reason)
async def edit_enter_reason(message: Message, state: FSMContext, db_user: User):
    reason = message.text.strip()
    if len(reason) < 10:
        return await message.answer("Причина слишком короткая. Минимум 10 символов.")

    # Delete user's text message
    try:
        await message.delete()
    except Exception:
        pass

    data = await state.get_data()
    async with async_session() as session:
        await cs.edit_shift(session, data["shift_id"], data["new_hours"], reason, db_user.id)

    cook_name = data.get("cook_name", "?")
    await common_mod.bot_instance.edit_message_text(
        chat_id=data["chat_id"],
        message_id=data["msg_id"],
        text=(
            f"✅ {cook_name}: {fmt_hours(data['old_hours'])} → {fmt_hours(data['new_hours'])} ч\n"
            f"Причина: {reason}"
        ),
        reply_markup=back_menu_kb(),
    )
    await state.clear()


# --- Today's timesheet ---

@router.callback_query(F.data == "menu:timesheet")
async def today_timesheet(cb: CallbackQuery, db_user: User | None):
    if not _is_sous_chef_or_owner(db_user):
        return await cb.answer("Нет доступа.", show_alert=True)

    async with async_session() as session:
        cooks = await cs.get_active_cooks(session)
        shifts = await cs.get_shifts_for_date(session, date.today())

    entered_ids = {s.cook_id for s in shifts}
    hours_map = {s.cook_id: s.hours_worked for s in shifts}

    lines = [f"📋 Табель за {date.today():%d.%m.%Y}:", ""]
    total_hours = 0
    for c in cooks:
        if c.id in entered_ids:
            h = float(hours_map[c.id])
            total_hours += h
            lines.append(f"✅ {c.name} — {fmt_hours(h)} ч")
        else:
            lines.append(f"⏳ {c.name} — не внесено")

    lines.append("")
    lines.append(f"Итого часов: {fmt_hours(total_hours)}")
    await cb.message.edit_text("\n".join(lines), reply_markup=back_menu_kb())
    await cb.answer()


# --- Revenue (manual input) ---

@router.callback_query(F.data == "menu:revenue")
async def start_set_revenue(cb: CallbackQuery, state: FSMContext, db_user: User | None):
    if not _is_sous_chef_or_owner(db_user):
        return await cb.answer("Нет доступа.", show_alert=True)
    await state.set_state(SetRevenueFSM.enter_amount)
    await cb.message.edit_text(
        "💰 Введите выручку за сегодня (тенге):",
        reply_markup=cancel_inline_kb(),
    )
    await state.update_data(msg_id=cb.message.message_id, chat_id=cb.message.chat.id)
    await cb.answer()


@router.message(SetRevenueFSM.enter_amount)
async def enter_revenue(message: Message, state: FSMContext, db_user: User):
    try:
        amount = float(message.text.replace(",", ".").replace(" ", ""))
        if amount < 0:
            raise ValueError
    except (ValueError, TypeError):
        return await message.answer("Введите корректную сумму.")

    # Delete user's text message
    try:
        await message.delete()
    except Exception:
        pass

    data = await state.get_data()

    async with async_session() as session:
        await cs.set_revenue(session, date.today(), amount, db_user.id)

    await common_mod.bot_instance.edit_message_text(
        chat_id=data["chat_id"],
        message_id=data["msg_id"],
        text=f"✅ Выручка: {amount:,.0f} тг записана ({date.today():%d.%m.%Y})",
        reply_markup=back_menu_kb(),
    )
    await state.clear()


# --- Shift report ---

@router.callback_query(F.data == "menu:report")
async def shift_report(cb: CallbackQuery, db_user: User | None):
    if not _is_sous_chef_or_owner(db_user):
        return await cb.answer("Нет доступа.", show_alert=True)
    async with async_session() as session:
        text = await daily_report(session, date.today())
    await cb.message.edit_text(text, reply_markup=back_menu_kb())
    await cb.answer()


# --- Repeat yesterday's shifts ---

@router.callback_query(F.data == "menu:repeat_yesterday")
async def repeat_yesterday(cb: CallbackQuery, db_user: User | None):
    if not _is_sous_chef_or_owner(db_user):
        return await cb.answer("Нет доступа.", show_alert=True)
    yesterday = date.today() - timedelta(days=1)
    async with async_session() as session:
        shifts = await cs.get_shifts_for_date(session, yesterday)
        if not shifts:
            await cb.message.edit_text("Вчера смен не было.", reply_markup=back_menu_kb())
            return await cb.answer()
        added = []
        skipped = []
        for s in shifts:
            try:
                await cs.add_shift(
                    session, s.cook_id, date.today(),
                    float(s.hours_worked), db_user.id, bool(s.is_extra),
                )
                added.append(f"\u2705 {s.cook.name} \u2014 {fmt_hours(float(s.hours_worked))} ч")
            except ValueError:
                skipped.append(f"\u23ed {s.cook.name} \u2014 уже есть")
        lines = ["\U0001f504 Повтор вчерашних смен:", ""]
        lines.extend(added)
        if skipped:
            lines.append("")
            lines.extend(skipped)
        await cb.message.edit_text("\n".join(lines), reply_markup=back_menu_kb())
    await cb.answer()


# --- Audit: recent shift edits ---

@router.callback_query(F.data == "menu:audit")
async def show_audit(cb: CallbackQuery, db_user: User | None):
    if not _is_sous_chef_or_owner(db_user):
        return await cb.answer("Нет доступа.", show_alert=True)
    async with async_session() as session:
        edits = await cs.get_recent_edits(session, limit=10)
        if not edits:
            await cb.message.edit_text("\U0001f4dc Правок пока нет.", reply_markup=back_menu_kb())
            return await cb.answer()
        # Fetch editor names
        editor_ids = {e.edited_by for e in edits}
        from sqlalchemy import select as sa_select
        result = await session.execute(
            sa_select(User).where(User.id.in_(editor_ids))
        )
        editors = {u.id: (u.name or str(u.telegram_id)) for u in result.scalars().all()}

    lines = ["\U0001f4dc Последние правки:", ""]
    for e in edits:
        cook_name = e.shift.cook.name if e.shift and e.shift.cook else "?"
        editor_name = editors.get(e.edited_by, "?")
        dt = e.edited_at.strftime("%d.%m") if e.edited_at else "?"
        lines.append(
            f"{dt} {cook_name}: {fmt_hours(float(e.old_hours))}\u2192"
            f"{fmt_hours(float(e.new_hours))} ч ({e.reason}) \u2014 {editor_name}"
        )
    await cb.message.edit_text("\n".join(lines), reply_markup=back_menu_kb())
    await cb.answer()
