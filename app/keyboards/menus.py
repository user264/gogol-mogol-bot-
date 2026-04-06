"""Role-based reply keyboards."""
from __future__ import annotations
from typing import Union
from aiogram.types import ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton


def main_menu_reply(role: str) -> Union[ReplyKeyboardMarkup, ReplyKeyboardRemove]:
    """Minimal reply keyboard — just the Menu button."""
    if role in ("pending", None):
        return ReplyKeyboardRemove()
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📋 Меню")]],
        resize_keyboard=True,
    )


# Legacy — kept for reference but no longer used for actions.
def main_menu(role: str) -> ReplyKeyboardMarkup:
    return main_menu_reply(role)
