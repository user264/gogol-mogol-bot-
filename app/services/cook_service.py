"""CRUD operations for cooks, rates, shifts."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Cook, CookRate, Shift, ShiftEdit, User, DailyRevenue, SystemConfig


# --- Cooks ---

async def add_cook(session: AsyncSession, name: str, hourly_rate: float, telegram_id: int | None = None) -> Cook:
    cook = Cook(name=name, telegram_id=telegram_id)
    session.add(cook)
    await session.flush()
    rate = CookRate(cook_id=cook.id, hourly_rate=hourly_rate, valid_from=date.today())
    session.add(rate)
    await session.commit()
    return cook


async def delete_cook(session: AsyncSession, cook_id: int) -> tuple:
    """Delete cook and all related data. Returns (name, list of telegram_ids of deleted users)."""
    cook = await session.get(Cook, cook_id)
    if not cook:
        return None, []
    name = cook.name
    deleted_tg_ids = []
    # Delete linked users (by cook_id AND by cook's telegram_id to catch orphans)
    linked_users_q = select(User).where(User.cook_id == cook_id)
    if cook.telegram_id:
        linked_users_q = select(User).where(
            (User.cook_id == cook_id) | (User.telegram_id == cook.telegram_id)
        )
    for u in (await session.execute(linked_users_q)).scalars().all():
        deleted_tg_ids.append(u.telegram_id)
        await session.delete(u)
    # Delete shift edits → shifts
    shifts = (await session.execute(select(Shift).where(Shift.cook_id == cook_id))).scalars().all()
    for s in shifts:
        edits = (await session.execute(select(ShiftEdit).where(ShiftEdit.shift_id == s.id))).scalars().all()
        for e in edits:
            await session.delete(e)
        await session.delete(s)
    # Delete rates
    for r in (await session.execute(select(CookRate).where(CookRate.cook_id == cook_id))).scalars().all():
        await session.delete(r)
    await session.delete(cook)
    await session.commit()
    return name, deleted_tg_ids


async def get_active_cooks(session: AsyncSession) -> list[Cook]:
    result = await session.execute(
        select(Cook).where(Cook.is_active == True).order_by(Cook.name)
    )
    return list(result.scalars().all())


async def update_rate(session: AsyncSession, cook_id: int, new_rate: float) -> CookRate:
    today = date.today()
    result = await session.execute(
        select(CookRate).where(
            CookRate.cook_id == cook_id,
            CookRate.valid_to.is_(None),
        )
    )
    old = result.scalar_one_or_none()
    if old:
        old.valid_to = today
    rate = CookRate(cook_id=cook_id, hourly_rate=new_rate, valid_from=today)
    session.add(rate)
    await session.commit()
    return rate


async def get_rate_on_date(session: AsyncSession, cook_id: int, d: date) -> Decimal:
    result = await session.execute(
        select(CookRate).where(
            CookRate.cook_id == cook_id,
            CookRate.valid_from <= d,
            (CookRate.valid_to.is_(None)) | (CookRate.valid_to > d),
        ).order_by(CookRate.valid_from.desc()).limit(1)
    )
    rate = result.scalar_one_or_none()
    return Decimal(str(rate.hourly_rate)) if rate else Decimal("0")


# --- Shifts ---

async def add_shift(session: AsyncSession, cook_id: int, shift_date: date, hours: float, entered_by: int, is_extra: bool = False) -> Shift:
    existing = await session.execute(
        select(Shift).where(Shift.cook_id == cook_id, Shift.shift_date == shift_date)
    )
    if existing.scalar_one_or_none():
        raise ValueError("shift_exists")
    shift = Shift(cook_id=cook_id, shift_date=shift_date, hours_worked=hours, is_extra=is_extra, entered_by=entered_by)
    session.add(shift)
    await session.commit()
    return shift


async def edit_shift(session: AsyncSession, shift_id: int, new_hours: float, reason: str, edited_by: int) -> Shift:
    shift = await session.get(Shift, shift_id)
    if not shift:
        raise ValueError("shift_not_found")
    edit = ShiftEdit(
        shift_id=shift.id,
        edited_by=edited_by,
        old_hours=float(shift.hours_worked),
        new_hours=new_hours,
        reason=reason,
    )
    session.add(edit)
    shift.hours_worked = new_hours
    await session.commit()
    return shift


async def get_shifts_for_date(session: AsyncSession, d: date) -> list[Shift]:
    result = await session.execute(
        select(Shift).options(selectinload(Shift.cook)).where(Shift.shift_date == d)
    )
    return list(result.scalars().all())


async def get_shifts_for_cook_period(session: AsyncSession, cook_id: int, start: date, end: date) -> list[Shift]:
    result = await session.execute(
        select(Shift).where(
            Shift.cook_id == cook_id,
            Shift.shift_date >= start,
            Shift.shift_date <= end,
        ).order_by(Shift.shift_date)
    )
    return list(result.scalars().all())


async def get_shift_by_cook_date(session: AsyncSession, cook_id: int, d: date) -> Shift | None:
    result = await session.execute(
        select(Shift).where(Shift.cook_id == cook_id, Shift.shift_date == d)
    )
    return result.scalar_one_or_none()


# --- Revenue ---

async def set_revenue(session: AsyncSession, d: date, revenue: float, entered_by: int) -> DailyRevenue:
    result = await session.execute(select(DailyRevenue).where(DailyRevenue.date == d))
    existing = result.scalar_one_or_none()
    if existing:
        existing.revenue = revenue
        existing.source = "manual"
        existing.entered_by = entered_by
    else:
        existing = DailyRevenue(date=d, revenue=revenue, source="manual", entered_by=entered_by)
        session.add(existing)
    await session.commit()
    return existing


async def get_revenue(session: AsyncSession, d: date) -> DailyRevenue | None:
    result = await session.execute(select(DailyRevenue).where(DailyRevenue.date == d))
    return result.scalar_one_or_none()


# --- Config ---

async def get_config(session: AsyncSession, key: str) -> str | None:
    result = await session.execute(select(SystemConfig).where(SystemConfig.key == key))
    cfg = result.scalar_one_or_none()
    return cfg.value if cfg else None


async def set_config(session: AsyncSession, key: str, value: str, user_id: int) -> None:
    result = await session.execute(select(SystemConfig).where(SystemConfig.key == key))
    cfg = result.scalar_one_or_none()
    if cfg:
        cfg.value = value
        cfg.updated_by = user_id
    else:
        session.add(SystemConfig(key=key, value=value, updated_by=user_id))
    await session.commit()


# --- Users ---

async def get_user_by_tg(session: AsyncSession, telegram_id: int) -> User | None:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def create_user(session: AsyncSession, telegram_id: int, role: str, cook_id: int | None = None, name: str | None = None) -> User:
    user = User(telegram_id=telegram_id, name=name, role=role, cook_id=cook_id)
    session.add(user)
    await session.commit()
    return user


async def get_all_users(session: AsyncSession) -> list[User]:
    result = await session.execute(
        select(User).where(
            User.role != "pending",
            # Exclude phantom cooks: role=cook but no linked cook record
            ~((User.role == "cook") & (User.cook_id.is_(None))),
        ).order_by(User.id)
    )
    return list(result.scalars().all())


async def get_pending_users(session: AsyncSession) -> list[User]:
    result = await session.execute(select(User).where(User.role == "pending").order_by(User.id))
    return list(result.scalars().all())


async def update_user_role(session: AsyncSession, user_id: int, new_role: str, cook_id: int | None = None) -> User:
    user = await session.get(User, user_id)
    user.role = new_role
    user.cook_id = cook_id
    await session.commit()
    return user


async def update_user_name(session: AsyncSession, telegram_id: int, name: str) -> None:
    user = await get_user_by_tg(session, telegram_id)
    if user and user.name != name:
        user.name = name
        await session.commit()


def display_name(user: User) -> str:
    return user.name or str(user.telegram_id)


async def get_recent_edits(session: AsyncSession, limit: int = 10) -> list:
    """Return last N shift edits with related shift->cook loaded."""
    result = await session.execute(
        select(ShiftEdit)
        .options(selectinload(ShiftEdit.shift).selectinload(Shift.cook))
        .order_by(ShiftEdit.edited_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
