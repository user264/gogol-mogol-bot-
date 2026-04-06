"""Manager handlers: manual revenue entry, shift report."""
from __future__ import annotations

from datetime import date

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.database import async_session
from app.models import User, Role
from app.handlers.states import SetRevenueFSM
from app.keyboards.inline import cancel_inline_kb
from app.keyboards.menus import main_menu
from app.services import cook_service as cs
from app.services.reports import daily_report

router = Router()


def _can_manage(user: User | None) -> bool:
    return user is not None and user.role in ("manager", "owner")


@router.message(F.text.in_({"💰 Выручка", "/set_revenue"}))
async def start_set_revenue(message: Message, state: FSMContext, db_user: User | None):
    if not _can_manage(db_user):
        return await message.answer("Нет доступа.")
    await state.set_state(SetRevenueFSM.enter_amount)
    await message.answer("Введите сумму выручки за сегодня (тенге):", reply_markup=cancel_inline_kb())


@router.message(SetRevenueFSM.enter_amount)
async def enter_revenue(message: Message, state: FSMContext, db_user: User):
    try:
        amount = float(message.text.replace(",", ".").replace(" ", ""))
        if amount < 0:
            raise ValueError
    except (ValueError, TypeError):
        return await message.answer("Введите корректную сумму.")

    async with async_session() as session:
        await cs.set_revenue(session, date.today(), amount, db_user.id)
    await message.answer(
        f"Выручка записана: {date.today():%d.%m.%Y} — {amount:,.0f} тг (ручной ввод)\n"
        "Используйте меню для следующего действия.",
        reply_markup=main_menu(db_user.role),
    )
    await state.clear()


@router.message(F.text == "📊 Отчёт")
async def shift_report(message: Message, db_user: User | None):
    if not _can_manage(db_user):
        return await message.answer("Нет доступа.")
    async with async_session() as session:
        text = await daily_report(session, date.today())
    await message.answer(text)
