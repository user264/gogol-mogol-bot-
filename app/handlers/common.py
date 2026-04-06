"""Common handlers: /start, role-based menu, cancel, back-to-menu."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup

from sqlalchemy import select

from app.database import async_session
from app.models import User, Role
from app.keyboards.menus import main_menu_reply
from app.keyboards.inline import menu_kb, back_menu_kb
from app.services import cook_service as cs

router = Router()

# Separate router for "Отмена" and "back_to_menu" — included FIRST in main.py
cancel_router = Router()

bot_instance = None

ROLE_LABELS = {"owner": "Владелец", "sous_chef": "Су-шеф", "cook": "Повар"}


def set_bot(bot):
    global bot_instance
    bot_instance = bot


async def show_menu(target, db_user, state=None, view_role=None):
    """Send or edit message to show main menu. target can be Message or CallbackQuery.
    view_role overrides the displayed role (for owner's "view as" feature)."""
    real_role = db_user.role
    display_role = view_role or real_role

    # Build status line for managers
    status = ""
    if display_role in ("sous_chef", "owner"):
        try:
            async with async_session() as session:
                cooks = await cs.get_active_cooks(session)
                shifts = await cs.get_shifts_for_date(session, date.today())
                entered = len({s.cook_id for s in shifts})
                total = len(cooks)
                rev = await cs.get_revenue(session, date.today())

                status = f"\n\n📊 Сегодня: {entered}/{total} поваров"
                if rev:
                    status += f" • Выручка: {Decimal(str(rev.revenue)):,.0f} тг"
                else:
                    status += " • Выручка: ❌"
        except Exception:
            pass

    view_label = ""
    if view_role and view_role != real_role:
        view_label = f" (просмотр как {ROLE_LABELS.get(view_role, view_role)})"

    text = f"Главное меню • {ROLE_LABELS.get(real_role, real_role)}{view_label}{status}"
    kb = menu_kb(display_role)
    # Add "back to owner" button when viewing as another role
    if view_role and view_role != real_role:
        from aiogram.types import InlineKeyboardButton
        kb = InlineKeyboardMarkup(
            inline_keyboard=list(kb.inline_keyboard) + [
                [InlineKeyboardButton(text="↩️ Вернуться к Владелец", callback_data="viewas:owner_back")]
            ]
        )
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=kb)
        except Exception:
            await target.message.answer(text, reply_markup=kb)
    else:
        msg = await target.answer(text, reply_markup=kb)
        if state:
            await state.update_data(menu_msg_id=msg.message_id)


# --- Cancel (inline) ---

@cancel_router.callback_query(F.data == "cancel_fsm")
async def cancel_fsm_inline(cb: CallbackQuery, state: FSMContext, db_user: User | None):
    """Cancel any active FSM state via inline button — return to menu."""
    await state.clear()
    if db_user and db_user.role not in ("pending",):
        await show_menu(cb, db_user)
    else:
        await cb.message.edit_text("Отменено.")
    await cb.answer()


# --- Back to menu ---

@cancel_router.callback_query(F.data == "back_to_menu")
async def back_to_menu(cb: CallbackQuery, state: FSMContext, db_user: User | None):
    data = await state.get_data()
    view_as = data.get("view_as")
    view_as_cook_id = data.get("view_as_cook_id")
    await state.clear()
    if view_as:
        await state.update_data(view_as=view_as, view_as_cook_id=view_as_cook_id)
    if db_user and db_user.role not in ("pending",):
        await show_menu(cb, db_user, state, view_role=view_as)
    else:
        await cb.message.edit_text("Отменено.")
    await cb.answer()


# --- View as role (owner only) ---

@cancel_router.callback_query(F.data.startswith("viewas:"))
async def view_as_role(cb: CallbackQuery, state: FSMContext, db_user: User | None):
    if not db_user or db_user.role != "owner":
        return await cb.answer("Нет доступа.", show_alert=True)
    target_role = cb.data.split(":")[1]
    if target_role == "owner_back":
        await state.clear()
        await show_menu(cb, db_user)
        return await cb.answer()
    if target_role == "cook":
        # Show cook list to pick which cook to view as
        async with async_session() as session:
            cooks = await cs.get_active_cooks(session)
        if not cooks:
            await cb.answer("Нет активных поваров.", show_alert=True)
            return
        from aiogram.types import InlineKeyboardButton
        buttons = [
            [InlineKeyboardButton(text=c.name, callback_data=f"viewcook:{c.id}")]
            for c in cooks
        ]
        buttons.append([InlineKeyboardButton(text="Отмена", callback_data="cancel_fsm")])
        await cb.message.edit_text(
            "Смотреть как повар:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
        return await cb.answer()
    await state.update_data(view_as=target_role, view_as_cook_id=None)
    await show_menu(cb, db_user, state, view_role=target_role)
    await cb.answer()


@cancel_router.callback_query(F.data.startswith("viewcook:"))
async def view_as_cook_pick(cb: CallbackQuery, state: FSMContext, db_user: User | None):
    if not db_user or db_user.role != "owner":
        return await cb.answer("Нет доступа.", show_alert=True)
    cook_id = int(cb.data.split(":")[1])
    await state.update_data(view_as="cook", view_as_cook_id=cook_id)
    await show_menu(cb, db_user, state, view_role="cook")
    await cb.answer()


# --- Cancel (text) ---

@cancel_router.message(F.text == "Отмена")
async def cancel_fsm(message: Message, state: FSMContext, db_user: User | None):
    """Cancel any active FSM state and return to main menu."""
    current = await state.get_state()
    await state.clear()
    if not current:
        await message.answer("Нечего отменять.")
        return
    role = db_user.role if db_user else None
    if role and role not in ("pending",):
        await message.answer("Действие отменено.", reply_markup=main_menu_reply(role))
    else:
        await message.answer("Действие отменено.")


async def _notify_managers(name: str) -> None:
    """Send notification to all sous_chefs and owners about new pending user."""
    if not bot_instance:
        return
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.role.in_(["owner", "sous_chef"]))
        )
        managers = result.scalars().all()

    for m in managers:
        try:
            await bot_instance.send_message(
                m.telegram_id,
                f"Новый сотрудник {name} хочет заступить на смену.\n"
                f"Назначьте роль: 📋 Меню → Сотрудники"
            )
        except Exception:
            pass


# --- /start ---

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, db_user: User | None, **kwargs):
    if not db_user:
        tg = message.from_user
        name = tg.full_name or tg.username or str(tg.id)
        async with async_session() as session:
            existing = await cs.get_user_by_tg(session, tg.id)
            if not existing:
                await cs.create_user(session, tg.id, "pending", name=name)
                await _notify_managers(name)
        await message.answer(
            f"{name}, вы добавлены в очередь.\n"
            "Су-шеф или владелец назначит вам роль."
        )
        return
    if db_user.role == "pending":
        await message.answer("Ожидайте — вам ещё не назначена роль.")
        return
    # Existing user — send reply keyboard + inline menu
    await message.answer("👇", reply_markup=main_menu_reply(db_user.role))
    await show_menu(message, db_user, state)


# --- "📋 Меню" reply button ---

@router.message(F.text == "📋 Меню")
async def menu_button(message: Message, state: FSMContext, db_user: User | None):
    if not db_user or db_user.role in ("pending",):
        return await message.answer("Нажмите /start чтобы начать.")
    await state.clear()
    await show_menu(message, db_user, state)


# --- Fallback ---

@router.message()
async def fallback(message: Message, db_user: User | None, **kwargs):
    """Catch all unhandled messages — if user deleted, prompt to /start."""
    if not db_user or db_user.role == "pending":
        from aiogram.types import ReplyKeyboardRemove
        await message.answer(
            "Нажмите /start чтобы начать.",
            reply_markup=ReplyKeyboardRemove(),
        )
