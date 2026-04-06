from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Optional, List

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, ForeignKey,
    Numeric, String, Text, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Role(str, enum.Enum):
    owner = "owner"
    manager = "manager"
    sous_chef = "sous_chef"
    cook = "cook"


class RevenueSource(str, enum.Enum):
    poster_auto = "poster_auto"
    manual = "manual"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    role: Mapped[str] = mapped_column(String(20))
    cook_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cooks.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    cook: Mapped[Optional[Cook]] = relationship(back_populates="user")

    @property
    def role_enum(self) -> Role:
        return Role(self.role)


class Cook(Base):
    __tablename__ = "cooks"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[Optional[User]] = relationship(back_populates="cook")
    rates: Mapped[List[CookRate]] = relationship(back_populates="cook", order_by="CookRate.valid_from.desc()")
    shifts: Mapped[List[Shift]] = relationship(back_populates="cook")


class CookRate(Base):
    __tablename__ = "cook_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    cook_id: Mapped[int] = mapped_column(ForeignKey("cooks.id"))
    hourly_rate: Mapped[float] = mapped_column(Numeric(10, 2))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    cook: Mapped[Cook] = relationship(back_populates="rates")


class Shift(Base):
    __tablename__ = "shifts"

    id: Mapped[int] = mapped_column(primary_key=True)
    cook_id: Mapped[int] = mapped_column(ForeignKey("cooks.id"))
    shift_date: Mapped[date] = mapped_column(Date)
    hours_worked: Mapped[float] = mapped_column(Numeric(4, 2))
    is_extra: Mapped[bool] = mapped_column(Boolean, default=False)
    entered_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    cook: Mapped[Cook] = relationship(back_populates="shifts")
    edits: Mapped[List[ShiftEdit]] = relationship(back_populates="shift")


class ShiftEdit(Base):
    __tablename__ = "shift_edits"

    id: Mapped[int] = mapped_column(primary_key=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"))
    edited_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    old_hours: Mapped[float] = mapped_column(Numeric(4, 2))
    new_hours: Mapped[float] = mapped_column(Numeric(4, 2))
    reason: Mapped[str] = mapped_column(Text)
    edited_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    shift: Mapped[Shift] = relationship(back_populates="edits")


class DailyRevenue(Base):
    __tablename__ = "daily_revenue"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, unique=True)
    revenue: Mapped[float] = mapped_column(Numeric(12, 2))
    source: Mapped[str] = mapped_column(String(20))
    operator_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    entered_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SystemConfig(Base):
    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
