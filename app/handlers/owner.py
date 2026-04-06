"""Owner handlers: manage cooks, rates, config, reports, CSV."""
from __future__ import annotations

from datetime import date

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton

from app.database import async_session
from app.models import User, Role, Cook
from app.handlers.states import (
    AddCookFSM, EditRateFSM, SetConfigFSM, MonthlyReportFSM,
    AddUserFSM, DeactivateCookFSM, ChangeRoleFSM,
)
from app.keyboards.inline import cook_list_kb, with_cancel, cancel_inline_kb, back_menu_kb
from app.keyboards.menus import main_menu_reply
from app.services import cook_service as cs
from app.services.cook_service import display_name
from app.services.reports import period_report, cook_period_report, period_csv, period_label
from app.handlers import common as common_mod

router = Router()


ROLE_LABELS = {
    "owner": "Владелец",
    "sous_chef": "Су-шеф",
    "cook": "Повар",
}


async def _send_new_menu(user: User) -> None:
    """Send updated menu to user after role change."""
    if not common_mod.bot_instance or user.role == "pending":
        return
    try:
        await common_mod.bot_instance.send_message(
            user.telegram_id,
            f"Вам назначена роль: {ROLE_LABELS.get(user.role, user.role)}",
            reply_markup=main_menu_reply(user.role),
        )
    except Exception:
        pass


async def _assign_cook_role(session, user_id: int, hourly_rate: float = 0) -> tuple:
    """Assign cook role: auto-create cook record, return (user, cook_name)."""
    user = await session.get(User, user_id)
    name = user.name or str(user.telegram_id)
    cook = await cs.add_cook(session, name, hourly_rate, user.telegram_id)
    user = await cs.update_user_role(session, user_id, "cook", cook.id)
    return user, cook.name


def _is_owner(user: User | None) -> bool:
    return user is not None and user.role == "owner"


def _can_manage_staff(user: User | None) -> bool:
    return user is not None and user.role in ("owner", "sous_chef")


# --- Manage staff (via inline menu) ---

@router.callback_query(F.data == "menu:staff")
async def manage_staff(cb: CallbackQuery, db_user: User | None):
    if not _can_manage_staff(db_user):
        return await cb.answer("Нет доступа.", show_alert=True)

    async with async_session() as session:
        cooks = await cs.get_active_cooks(session)

    cook_lines = "\n".join(f"  {c.name}" for c in cooks) if cooks else "  (пусто)"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Добавить повара", callback_data="staff:add_cook")],
        [InlineKeyboardButton(text="Изменить ставку", callback_data="staff:edit_rate")],
        [InlineKeyboardButton(text="Удалить повара", callback_data="staff:delete_cook")],
        [InlineKeyboardButton(text="Добавить пользователя", callback_data="staff:add_user")],
        [InlineKeyboardButton(text="Изменить роль", callback_data="staff:change_role")],
        [InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")],
    ])
    await cb.message.edit_text(f"👥 Повара:\n{cook_lines}\n\nВыберите действие:", reply_markup=kb)
    await cb.answer()


# --- Add cook (via buttons) ---

@router.callback_query(F.data == "staff:add_cook")
async def staff_add_cook(cb: CallbackQuery, state: FSMContext, db_user: User | None):
    if not _can_manage_staff(db_user):
        return await cb.answer("Нет доступа.", show_alert=True)
    await state.set_state(AddCookFSM.enter_name)
    await state.update_data(msg_id=cb.message.message_id, chat_id=cb.message.chat.id)
    await cb.message.edit_text("Введите имя повара:", reply_markup=cancel_inline_kb())
    await cb.answer()


@router.message(AddCookFSM.enter_name)
async def cook_name(message: Message, state: FSMContext):
    try:
        await message.delete()
    except Exception:
        pass
    data = await state.get_data()
    await state.update_data(name=message.text.strip())
    await state.set_state(AddCookFSM.enter_rate)
    await common_mod.bot_instance.edit_message_text(
        chat_id=data["chat_id"],
        message_id=data["msg_id"],
        text=f"👨\u200d🍳 {message.text.strip()}\nВведите часовую ставку (тенге/час):",
        reply_markup=cancel_inline_kb(),
    )


@router.message(AddCookFSM.enter_rate)
async def cook_rate(message: Message, state: FSMContext):
    try:
        rate = float(message.text.replace(",", "."))
        if rate <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return await message.answer("Введите корректную ставку.")
    try:
        await message.delete()
    except Exception:
        pass
    data = await state.get_data()
    await state.update_data(rate=rate)
    await state.set_state(AddCookFSM.enter_telegram)
    await common_mod.bot_instance.edit_message_text(
        chat_id=data["chat_id"],
        message_id=data["msg_id"],
        text=f"👨\u200d🍳 {data.get('name', '?')}, ставка {rate} тг/ч\nВведите Telegram ID повара (или 0 если неизвестен):",
        reply_markup=cancel_inline_kb(),
    )


@router.message(AddCookFSM.enter_telegram)
async def cook_telegram(message: Message, state: FSMContext, db_user: User | None):
    try:
        tg_id = int(message.text.strip())
    except ValueError:
        return await message.answer("Введите числовой Telegram ID (или 0).")

    try:
        await message.delete()
    except Exception:
        pass

    data = await state.get_data()
    async with async_session() as session:
        cook = await cs.add_cook(session, data["name"], data["rate"], tg_id if tg_id else None)
    await common_mod.bot_instance.edit_message_text(
        chat_id=data["chat_id"],
        message_id=data["msg_id"],
        text=f"✅ Повар {data['name']} добавлен (id={cook.id}, ставка {data['rate']} тг/ч).",
        reply_markup=back_menu_kb(),
    )
    await state.clear()


# --- Edit rate (via buttons) ---

@router.callback_query(F.data == "staff:edit_rate")
async def staff_edit_rate(cb: CallbackQuery, state: FSMContext, db_user: User | None):
    if not _can_manage_staff(db_user):
        return await cb.answer("Нет доступа.", show_alert=True)
    async with async_session() as session:
        cooks = await cs.get_active_cooks(session)
    if not cooks:
        await cb.message.edit_text("Нет активных поваров.", reply_markup=back_menu_kb())
        return await cb.answer()
    await state.set_state(EditRateFSM.choose_cook)
    await state.update_data(msg_id=cb.message.message_id, chat_id=cb.message.chat.id)
    await cb.message.edit_text("Выберите повара:", reply_markup=with_cancel(cook_list_kb(cooks, "editrate")))
    await cb.answer()


@router.callback_query(EditRateFSM.choose_cook, F.data.startswith("editrate:"))
async def rate_pick_cook(cb: CallbackQuery, state: FSMContext):
    cook_id = int(cb.data.split(":")[1])
    await state.update_data(cook_id=cook_id)
    await state.set_state(EditRateFSM.enter_rate)
    await cb.message.edit_text("Введите новую ставку (тенге/час):", reply_markup=cancel_inline_kb())
    await cb.answer()


@router.message(EditRateFSM.enter_rate)
async def rate_enter(message: Message, state: FSMContext, db_user: User | None):
    try:
        rate = float(message.text.replace(",", "."))
        if rate <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return await message.answer("Введите корректную ставку.")

    try:
        await message.delete()
    except Exception:
        pass

    data = await state.get_data()
    async with async_session() as session:
        await cs.update_rate(session, data["cook_id"], rate)
    await common_mod.bot_instance.edit_message_text(
        chat_id=data["chat_id"],
        message_id=data["msg_id"],
        text=f"✅ Ставка обновлена: {rate} тг/ч.",
        reply_markup=back_menu_kb(),
    )
    await state.clear()


# --- Delete cook (via buttons) ---

@router.callback_query(F.data == "staff:delete_cook")
async def staff_delete_cook(cb: CallbackQuery, state: FSMContext, db_user: User | None):
    if not _can_manage_staff(db_user):
        return await cb.answer("Нет доступа.", show_alert=True)
    async with async_session() as session:
        cooks = await cs.get_active_cooks(session)
    if not cooks:
        await cb.message.edit_text("Нет активных поваров.", reply_markup=back_menu_kb())
        return await cb.answer()
    await state.set_state(DeactivateCookFSM.choose_cook)
    await cb.message.edit_text("Кого удалить?", reply_markup=with_cancel(cook_list_kb(cooks, "deact")))
    await cb.answer()


@router.callback_query(DeactivateCookFSM.choose_cook, F.data.startswith("deact:"))
async def deact_pick_cook(cb: CallbackQuery, state: FSMContext):
    cook_id = int(cb.data.split(":")[1])
    async with async_session() as session:
        cook = await session.get(Cook, cook_id)
        cook_name = cook.name if cook else "?"
    await state.update_data(cook_id=cook_id, cook_name=cook_name)
    await state.set_state(DeactivateCookFSM.confirm_delete)
    await cb.message.edit_text(
        f"Точно удалить {cook_name}? Все смены будут удалены.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Да", callback_data="deact_confirm:yes"),
                InlineKeyboardButton(text="Нет", callback_data="deact_confirm:no"),
            ]
        ]),
    )
    await cb.answer()


@router.callback_query(DeactivateCookFSM.confirm_delete, F.data.startswith("deact_confirm:"))
async def deact_confirm(cb: CallbackQuery, state: FSMContext, db_user: User | None):
    if cb.data.endswith(":no"):
        await state.clear()
        await cb.message.edit_text("Удаление отменено.", reply_markup=back_menu_kb())
        return await cb.answer()

    data = await state.get_data()
    cook_id = data["cook_id"]
    async with async_session() as session:
        name, deleted_tg_ids = await cs.delete_cook(session, cook_id)
    # Notify deleted users — remove keyboard and ask to restart
    from aiogram.types import ReplyKeyboardRemove
    if common_mod.bot_instance:
        for tg_id in deleted_tg_ids:
            try:
                await common_mod.bot_instance.send_message(
                    tg_id,
                    "Ваш доступ удалён. Нажмите /start чтобы подать заявку заново.",
                    reply_markup=ReplyKeyboardRemove(),
                )
            except Exception:
                pass
    await cb.message.edit_text(f"✅ Повар {name or '?'} удалён.", reply_markup=back_menu_kb())
    await state.clear()
    await cb.answer()


# --- Add user / assign role (via buttons) ---

@router.callback_query(F.data == "staff:add_user")
async def staff_add_user(cb: CallbackQuery, state: FSMContext, db_user: User | None):
    if not _can_manage_staff(db_user):
        return await cb.answer("Нет доступа.", show_alert=True)
    async with async_session() as session:
        pending = await cs.get_pending_users(session)
    if not pending:
        await cb.message.edit_text(
            "Нет ожидающих. Пусть человек напишет /start боту, потом назначите роль.",
            reply_markup=back_menu_kb(),
        )
        return await cb.answer()
    buttons = [
        [InlineKeyboardButton(text=display_name(u), callback_data=f"pickpend:{u.id}")]
        for u in pending
    ]
    await state.set_state(AddUserFSM.enter_telegram)
    await state.update_data(msg_id=cb.message.message_id, chat_id=cb.message.chat.id)
    await cb.message.edit_text("Ожидают назначения роли:", reply_markup=with_cancel(InlineKeyboardMarkup(inline_keyboard=buttons)))
    await cb.answer()


@router.callback_query(AddUserFSM.enter_telegram, F.data.startswith("pickpend:"))
async def add_user_pick_pending(cb: CallbackQuery, state: FSMContext):
    user_id = int(cb.data.split(":")[1])
    await state.update_data(target_user_id=user_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"role:{key}")]
        for key, label in ROLE_LABELS.items()
    ])
    await state.set_state(AddUserFSM.choose_role)
    await cb.message.edit_text("Выберите роль:", reply_markup=with_cancel(kb))
    await cb.answer()


@router.callback_query(AddUserFSM.choose_role, F.data.startswith("role:"))
async def add_user_pick_role(cb: CallbackQuery, state: FSMContext, db_user: User | None):
    role = cb.data.split(":")[1]
    data = await state.get_data()
    user_id = data["target_user_id"]

    if role == "cook":
        await state.update_data(new_role=role)
        await state.set_state(AddUserFSM.enter_rate)
        await cb.message.edit_text("Введите часовую ставку для повара (тенге/час):", reply_markup=cancel_inline_kb())
        return await cb.answer()

    async with async_session() as session:
        user = await cs.update_user_role(session, user_id, role)
    await _send_new_menu(user)
    await cb.message.edit_text(
        f"✅ {display_name(user)} — назначен {ROLE_LABELS[role]}.",
        reply_markup=back_menu_kb(),
    )
    await state.clear()
    await cb.answer()


@router.message(AddUserFSM.enter_rate)
async def add_user_enter_rate(message: Message, state: FSMContext, db_user: User | None):
    try:
        rate = float(message.text.replace(",", "."))
        if rate <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return await message.answer("Введите корректную ставку.")

    try:
        await message.delete()
    except Exception:
        pass

    data = await state.get_data()
    async with async_session() as session:
        user, cook_name = await _assign_cook_role(session, data["target_user_id"], rate)
    await _send_new_menu(user)
    await common_mod.bot_instance.edit_message_text(
        chat_id=data["chat_id"],
        message_id=data["msg_id"],
        text=f"✅ {display_name(user)} — назначен Повар ({cook_name}), ставка {rate} тг/ч.",
        reply_markup=back_menu_kb(),
    )
    await state.clear()


# --- Change role (via buttons) ---

@router.callback_query(F.data == "staff:change_role")
async def staff_change_role(cb: CallbackQuery, state: FSMContext, db_user: User | None):
    if not _can_manage_staff(db_user):
        return await cb.answer("Нет доступа.", show_alert=True)
    async with async_session() as session:
        users = await cs.get_all_users(session)
    if not users:
        await cb.message.edit_text("Нет пользователей.", reply_markup=back_menu_kb())
        return await cb.answer()
    buttons = []
    for u in users:
        label = f"{display_name(u)} — {ROLE_LABELS.get(u.role, u.role)}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"chrole:{u.id}")])
    await state.set_state(ChangeRoleFSM.choose_user)
    await state.update_data(msg_id=cb.message.message_id, chat_id=cb.message.chat.id)
    await cb.message.edit_text("Выберите пользователя:", reply_markup=with_cancel(InlineKeyboardMarkup(inline_keyboard=buttons)))
    await cb.answer()


@router.callback_query(ChangeRoleFSM.choose_user, F.data.startswith("chrole:"))
async def chrole_pick_user(cb: CallbackQuery, state: FSMContext):
    user_id = int(cb.data.split(":")[1])
    await state.update_data(target_user_id=user_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"newrole:{key}")]
        for key, label in ROLE_LABELS.items()
    ])
    await state.set_state(ChangeRoleFSM.choose_role)
    await cb.message.edit_text("Выберите новую роль:", reply_markup=with_cancel(kb))
    await cb.answer()


@router.callback_query(ChangeRoleFSM.choose_role, F.data.startswith("newrole:"))
async def chrole_pick_role(cb: CallbackQuery, state: FSMContext, db_user: User | None):
    new_role = cb.data.split(":")[1]
    data = await state.get_data()

    if new_role == "cook":
        await state.update_data(new_role=new_role)
        await state.set_state(ChangeRoleFSM.enter_rate)
        await cb.message.edit_text("Введите часовую ставку для повара (тенге/час):", reply_markup=cancel_inline_kb())
        return await cb.answer()

    async with async_session() as session:
        user = await cs.update_user_role(session, data["target_user_id"], new_role)
    await _send_new_menu(user)
    await cb.message.edit_text(
        f"✅ {display_name(user)} — роль изменена на {ROLE_LABELS[new_role]}.",
        reply_markup=back_menu_kb(),
    )
    await state.clear()
    await cb.answer()


@router.message(ChangeRoleFSM.enter_rate)
async def chrole_enter_rate(message: Message, state: FSMContext, db_user: User | None):
    try:
        rate = float(message.text.replace(",", "."))
        if rate <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return await message.answer("Введите корректную ставку.")

    try:
        await message.delete()
    except Exception:
        pass

    data = await state.get_data()
    async with async_session() as session:
        user, cook_name = await _assign_cook_role(session, data["target_user_id"], rate)
    await _send_new_menu(user)
    await common_mod.bot_instance.edit_message_text(
        chat_id=data["chat_id"],
        message_id=data["msg_id"],
        text=f"✅ {display_name(user)} — роль изменена на Повар ({cook_name}), ставка {rate} тг/ч.",
        reply_markup=back_menu_kb(),
    )
    await state.clear()


# --- Edit shift by owner (any date) ---

@router.message(Command("edit_shift"))
async def cmd_edit_shift(message: Message, db_user: User | None):
    if not _is_owner(db_user):
        return await message.answer("Нет доступа.")
    parts = message.text.split(maxsplit=4)
    if len(parts) < 5:
        return await message.answer("Формат: /edit_shift <cook_id> <YYYY-MM-DD> <hours> <причина>")
    try:
        cook_id = int(parts[1])
        shift_date = date.fromisoformat(parts[2])
        hours = float(parts[3])
        reason = parts[4]
    except (ValueError, IndexError):
        return await message.answer("Неверный формат. Пример: /edit_shift 1 2026-04-15 8 Корректировка по факту")
    if len(reason) < 10:
        return await message.answer("Причина — минимум 10 символов.")

    async with async_session() as session:
        shift = await cs.get_shift_by_cook_date(session, cook_id, shift_date)
        if not shift:
            return await message.answer("Смена не найдена.")
        await cs.edit_shift(session, shift.id, hours, reason, db_user.id)
    await message.answer(f"✅ Смена обновлена: {hours} ч. Причина: {reason}")


# --- System config ---

@router.callback_query(F.data == "menu:settings")
async def show_settings(cb: CallbackQuery, db_user: User | None):
    if not _is_owner(db_user):
        return await cb.answer("Нет доступа.", show_alert=True)
    async with async_session() as session:
        threshold = await cs.get_config(session, "revenue_threshold") or "200000"
        bonus_step = await cs.get_config(session, "bonus_step") or "6844"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Порог выручки: {threshold} тг", callback_data="cfg:revenue_threshold")],
        [InlineKeyboardButton(text=f"Шаг процента: {bonus_step} тг", callback_data="cfg:bonus_step")],
        [InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")],
    ])
    await cb.message.edit_text("⚙️ Настройки:", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("cfg:"))
async def pick_config_param(cb: CallbackQuery, state: FSMContext, db_user: User | None):
    if not _is_owner(db_user):
        return await cb.answer("Нет доступа.", show_alert=True)
    key = cb.data.split(":")[1]
    labels = {"revenue_threshold": "порог выручки (тенге)", "bonus_step": "шаг процента (тенге)"}
    await state.update_data(config_key=key, msg_id=cb.message.message_id, chat_id=cb.message.chat.id)
    await state.set_state(SetConfigFSM.enter_value)
    await cb.message.edit_text(f"Введите новое значение — {labels[key]}:", reply_markup=cancel_inline_kb())
    await cb.answer()


@router.message(SetConfigFSM.enter_value)
async def enter_config_value(message: Message, state: FSMContext, db_user: User):
    data = await state.get_data()
    key = data["config_key"]
    raw = message.text.strip().replace(",", ".").replace(" ", "")
    try:
        val = float(raw)
        if val < 0:
            raise ValueError
    except (ValueError, TypeError):
        return await message.answer("Введите корректное число.")

    try:
        await message.delete()
    except Exception:
        pass

    async with async_session() as session:
        await cs.set_config(session, key, raw, db_user.id)

    labels = {"revenue_threshold": "Порог выручки", "bonus_step": "Шаг процента"}
    await common_mod.bot_instance.edit_message_text(
        chat_id=data["chat_id"],
        message_id=data["msg_id"],
        text=f"✅ {labels[key]} = {raw}",
        reply_markup=back_menu_kb(),
    )
    await state.clear()


# --- Salary periods (16th — 15th) ---

def _generate_periods(count: int = 6) -> list[tuple[date, date]]:
    """Generate recent salary periods: 16th of month to 15th of next month."""
    today = date.today()
    if today.day >= 16:
        current_start = date(today.year, today.month, 16)
    else:
        m = today.month - 1 if today.month > 1 else 12
        y = today.year if today.month > 1 else today.year - 1
        current_start = date(y, m, 16)

    periods = []
    start = current_start
    for _ in range(count):
        if start.month == 12:
            end = date(start.year + 1, 1, 15)
        else:
            end = date(start.year, start.month + 1, 15)
        periods.append((start, end))
        # go back one period
        if start.month == 1:
            start = date(start.year - 1, 12, 16)
        else:
            start = date(start.year, start.month - 1, 16)

    periods.reverse()
    return periods


# --- Monthly report ---

@router.callback_query(F.data == "menu:monthly")
async def cmd_monthly(cb: CallbackQuery, state: FSMContext, db_user: User | None):
    if not _is_owner(db_user):
        return await cb.answer("Нет доступа.", show_alert=True)
    periods = _generate_periods()
    buttons = []
    for start, end in periods:
        label = f"{start:%d.%m} — {end:%d.%m.%Y}"
        cb_data = f"period:{start.isoformat()}:{end.isoformat()}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=cb_data)])
    buttons.append([InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")])
    await cb.message.edit_text(
        "📅 Выберите период:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await state.update_data(msg_id=cb.message.message_id, chat_id=cb.message.chat.id)
    await state.set_state(MonthlyReportFSM.choose_period)
    await cb.answer()


@router.callback_query(MonthlyReportFSM.choose_period, F.data.startswith("period:"))
async def monthly_pick_period(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split(":")
    start = date.fromisoformat(parts[1])
    end = date.fromisoformat(parts[2])
    await state.update_data(period_start=parts[1], period_end=parts[2])

    async with async_session() as session:
        cooks = await cs.get_active_cooks(session)
    buttons = [[InlineKeyboardButton(text="Все повара", callback_data="mrpt:all")]]
    for c in cooks:
        buttons.append([InlineKeyboardButton(text=c.name, callback_data=f"mrpt:{c.id}")])
    buttons.append([InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")])
    await cb.message.edit_text(
        f"📅 Период: {start:%d.%m} — {end:%d.%m.%Y}\nПо кому сформировать отчёт?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await state.set_state(MonthlyReportFSM.choose_cook)
    await cb.answer()


@router.callback_query(MonthlyReportFSM.choose_cook, F.data.startswith("mrpt:"))
async def monthly_pick_cook(cb: CallbackQuery, state: FSMContext, db_user: User | None):
    data = await state.get_data()
    start = date.fromisoformat(data["period_start"])
    end = date.fromisoformat(data["period_end"])
    choice = cb.data.split(":")[1]

    async with async_session() as session:
        if choice == "all":
            text = await period_report(session, start, end)
        else:
            text = await cook_period_report(session, int(choice), start, end)

    await cb.message.edit_text(text, reply_markup=back_menu_kb())
    await state.clear()
    await cb.answer()


# --- CSV export ---

@router.callback_query(F.data == "menu:csv")
async def export_csv(cb: CallbackQuery, db_user: User | None):
    if not _is_owner(db_user):
        return await cb.answer("Нет доступа.", show_alert=True)
    periods = _generate_periods()
    buttons = []
    for start, end in periods:
        label = f"{start:%d.%m} — {end:%d.%m.%Y}"
        cb_data = f"csv_p:{start.isoformat()}:{end.isoformat()}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=cb_data)])
    buttons.append([InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")])
    await cb.message.edit_text("📥 Выберите период для CSV:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await cb.answer()


@router.callback_query(F.data.startswith("csv_p:"))
async def csv_pick_period(cb: CallbackQuery, db_user: User | None):
    if not _is_owner(db_user):
        return await cb.answer("Нет доступа.", show_alert=True)
    parts = cb.data.split(":")
    start = date.fromisoformat(parts[1])
    end = date.fromisoformat(parts[2])
    async with async_session() as session:
        data = await period_csv(session, start, end)
    doc = BufferedInputFile(data, filename=f"report_{start:%d%m}_{end:%d%m%Y}.csv")
    await cb.message.answer_document(doc, caption=f"📥 Отчёт за {start:%d.%m} — {end:%d.%m.%Y}")
    # Edit the original message back to show a back button
    try:
        await cb.message.edit_text(
            f"📥 CSV за {start:%d.%m} — {end:%d.%m.%Y} отправлен.",
            reply_markup=back_menu_kb(),
        )
    except Exception:
        pass
    await cb.answer()
