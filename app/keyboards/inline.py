"""Inline keyboards for cook selection, date picking, confirmations, and main menu."""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from app.models import Cook


def with_cancel(kb: InlineKeyboardMarkup) -> InlineKeyboardMarkup:
    """Append a cancel button row to an inline keyboard."""
    buttons = list(kb.inline_keyboard) + [
        [InlineKeyboardButton(text="Отмена", callback_data="cancel_fsm")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def cancel_inline_kb() -> InlineKeyboardMarkup:
    """Standalone inline keyboard with just a cancel button."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена", callback_data="cancel_fsm")]
    ])


def back_menu_kb() -> InlineKeyboardMarkup:
    """Single 'back to menu' button."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")]
    ])


def menu_kb(role: str) -> InlineKeyboardMarkup:
    """Main inline menu based on role."""
    buttons = []
    if role == "cook":
        buttons.append([InlineKeyboardButton(text="📊 Моя статистика", callback_data="menu:my_stats")])
        buttons.append([
            InlineKeyboardButton(text="📄 Скачать PDF", callback_data="menu:my_pdf"),
            InlineKeyboardButton(text="✉️ Написать", callback_data="menu:feedback"),
        ])
    if role == "sous_chef":
        buttons.append([
            InlineKeyboardButton(text="\U0001f550 Часы", callback_data="menu:add_shift"),
            InlineKeyboardButton(text="\u2795 Доп.", callback_data="menu:add_extra"),
            InlineKeyboardButton(text="\U0001f504 Повтор вчера", callback_data="menu:repeat_yesterday"),
        ])
        buttons.append([
            InlineKeyboardButton(text="\u270f\ufe0f Редакт.", callback_data="menu:edit_shift"),
            InlineKeyboardButton(text="\U0001f4cb Табель", callback_data="menu:timesheet"),
        ])
        buttons.append([
            InlineKeyboardButton(text="\U0001f4b0 Выручка", callback_data="menu:revenue"),
            InlineKeyboardButton(text="\U0001f4b0 За прош. дни", callback_data="menu:revenue_past"),
        ])
        buttons.append([
            InlineKeyboardButton(text="\U0001f4ca Отчёт", callback_data="menu:report"),
        ])
        buttons.append([
            InlineKeyboardButton(text="\U0001f465 Сотрудники", callback_data="menu:staff"),
            InlineKeyboardButton(text="✉️ Написать", callback_data="menu:feedback"),
        ])
    if role == "owner":
        buttons.append([
            InlineKeyboardButton(text="\U0001f550 Часы", callback_data="menu:add_shift"),
            InlineKeyboardButton(text="\u2795 Доп.", callback_data="menu:add_extra"),
            InlineKeyboardButton(text="\U0001f504 Повтор вчера", callback_data="menu:repeat_yesterday"),
        ])
        buttons.append([
            InlineKeyboardButton(text="\u270f\ufe0f Редакт.", callback_data="menu:edit_shift"),
            InlineKeyboardButton(text="\U0001f4cb Табель", callback_data="menu:timesheet"),
        ])
        buttons.append([
            InlineKeyboardButton(text="\U0001f4b0 Выручка", callback_data="menu:revenue"),
            InlineKeyboardButton(text="\U0001f4b0 За прош. дни", callback_data="menu:revenue_past"),
        ])
        buttons.append([
            InlineKeyboardButton(text="\U0001f4ca Отчёт", callback_data="menu:report"),
        ])
        buttons.append([
            InlineKeyboardButton(text="\U0001f465 Сотрудники", callback_data="menu:staff"),
            InlineKeyboardButton(text="\u2699\ufe0f Настройки", callback_data="menu:settings"),
        ])
        buttons.append([
            InlineKeyboardButton(text="\U0001f4c5 Мес. отчёт", callback_data="menu:monthly"),
            InlineKeyboardButton(text="\U0001f4e5 CSV", callback_data="menu:csv"),
        ])
        buttons.append([
            InlineKeyboardButton(text="\U0001f4dc Правки", callback_data="menu:audit"),
        ])
        buttons.append([
            InlineKeyboardButton(text="\U0001f440 Вид: Су-шеф", callback_data="viewas:sous_chef"),
            InlineKeyboardButton(text="\U0001f440 Вид: Повар", callback_data="viewas:cook"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def cook_list_kb(cooks: list[Cook], prefix: str = "cook") -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=c.name, callback_data=f"{prefix}:{c.id}")]
        for c in cooks
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def date_pick_kb() -> InlineKeyboardMarkup:
    from datetime import date, timedelta
    today = date.today()
    yesterday = today - timedelta(days=1)
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"Сегодня ({today:%d.%m})", callback_data=f"date:{today.isoformat()}"),
            InlineKeyboardButton(text=f"Вчера ({yesterday:%d.%m})", callback_data=f"date:{yesterday.isoformat()}"),
        ]
    ])


def period_dates_kb(prefix: str = "revdate") -> InlineKeyboardMarkup:
    """Keyboard with all dates of the current salary period (16th-15th)."""
    from datetime import date, timedelta
    today = date.today()
    if today.day >= 16:
        start = today.replace(day=16)
        if today.month == 12:
            end = date(today.year + 1, 1, 15)
        else:
            end = date(today.year, today.month + 1, 15)
    else:
        if today.month == 1:
            start = date(today.year - 1, 12, 16)
        else:
            start = date(today.year, today.month - 1, 16)
        end = today.replace(day=15)

    dates = []
    d = start
    while d <= min(end, today):
        dates.append(d)
        d += timedelta(days=1)

    rows = []
    row = []
    for d in dates:
        row.append(InlineKeyboardButton(text=f"{d:%d.%m}", callback_data=f"{prefix}:{d.isoformat()}"))
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_kb(action: str = "confirm") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Подтвердить", callback_data=f"{action}:yes"),
            InlineKeyboardButton(text="Отмена", callback_data=f"{action}:no"),
        ]
    ])


def hours_kb() -> InlineKeyboardMarkup:
    """Hour selection keyboard for shift entry."""
    row1 = [InlineKeyboardButton(text=str(h), callback_data=f"hours:{h}") for h in [6, 7, 8, 9]]
    row2 = [InlineKeyboardButton(text=str(h), callback_data=f"hours:{h}") for h in [10, 11, 12]]
    row2.append(InlineKeyboardButton(text="Другое", callback_data="hours:custom"))
    cancel = [InlineKeyboardButton(text="Отмена", callback_data="cancel_fsm")]
    return InlineKeyboardMarkup(inline_keyboard=[row1, row2, cancel])
