"""Tests for payroll & bonus calculation."""
from decimal import Decimal

from app.services.calc import calc_bonus_percent, calc_day, calc_extra_coeff


def test_bonus_below_threshold():
    pct = calc_bonus_percent(Decimal("250000"), Decimal("270908"), Decimal("6844"))
    assert pct == 0


def test_bonus_at_threshold():
    """At threshold exactly → 10% base."""
    pct = calc_bonus_percent(Decimal("270908"), Decimal("270908"), Decimal("6844"))
    assert pct == 10


def test_bonus_above_threshold():
    """(350000 - 270908) / 6844 = 11 steps → 10 + 11 = 21%."""
    pct = calc_bonus_percent(Decimal("350000"), Decimal("270908"), Decimal("6844"))
    assert pct == 21


def test_bonus_500k():
    """(500000 - 270908) / 6844 = 33 steps → 10 + 33 = 43%."""
    pct = calc_bonus_percent(Decimal("500000"), Decimal("270908"), Decimal("6844"))
    assert pct == 43


def test_extra_coeff_8h():
    coeff = calc_extra_coeff({3: Decimal("8")})
    assert coeff == Decimal("0.2200")


def test_calc_day_no_bonus():
    cook_data = [(1, "A", Decimal("8"), Decimal("950"), False)]
    results, _, _, _, pct = calc_day(cook_data, Decimal("200000"), Decimal("270908"), Decimal("6844"))
    assert pct == 0
    assert results[0].bonus == Decimal("0")
    assert results[0].base_pay == Decimal("7600.00")


def test_calc_day_with_bonus():
    """Revenue 500k, threshold 270908, step 6844 → 43%.
    R: 12.5×950=11875, bonus=11875×43%=5106.25
    S: 12.5×1000=12500, bonus=12500×43%=5375.00"""
    cook_data = [
        (1, "R", Decimal("12.5"), Decimal("950"), False),
        (2, "S", Decimal("12.5"), Decimal("1000"), False),
    ]
    results, coeff, _, _, pct = calc_day(cook_data, Decimal("500000"), Decimal("270908"), Decimal("6844"))
    assert pct == 43
    assert coeff == Decimal("0")

    r = results[0]
    assert r.base_pay == Decimal("11875.00")
    assert r.bonus == Decimal("5106.25")
    assert r.total == Decimal("16981.25")

    s = results[1]
    assert s.base_pay == Decimal("12500.00")
    assert s.bonus == Decimal("5375.00")
    assert s.total == Decimal("17875.00")


def test_calc_day_with_extra_raises_threshold():
    """Extra cook 8h → coeff=0.22, threshold and step grow, percent drops."""
    cook_data = [
        (1, "A", Decimal("12"), Decimal("950"), False),
        (3, "C", Decimal("8"), Decimal("700"), True),
    ]
    results, coeff, adj_thr, adj_step, pct = calc_day(
        cook_data, Decimal("350000"), Decimal("270908"), Decimal("6844")
    )
    assert coeff == Decimal("0.2200")
    # adj_threshold = 270908 * 1.22 = 330507.76
    # adj_step = 6844 * 1.22 = 8349.68
    # steps = floor((350000 - 330507.76) / 8349.68) = floor(2.33) = 2
    # percent = 10 + 2 = 12
    assert pct == 12
