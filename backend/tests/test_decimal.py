"""Direct tests for the integer-only display rounding helper."""

from __future__ import annotations

import sys
from fractions import Fraction
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import _rounded_decimal  # noqa: E402


@pytest.mark.parametrize(
    "value,digits,expected",
    [
        (Fraction(0), 12, "0"),
        (Fraction(1), 12, "1"),
        (Fraction(-3), 12, "-3"),
        (Fraction(1, 3), 12, "0.333333333333"),
        (Fraction(2, 3), 12, "0.666666666667"),  # rounded up
        (Fraction(1, 7), 6, "0.142857"),
        (Fraction(10, 3), 6, "3.33333"),
        (Fraction(1000), 6, "1000"),
        (Fraction(123456789, 1000), 6, "123457"),  # 123456.789 rounds
        (Fraction(1, 100000), 3, "0.00001"),
        (Fraction(-1, 3), 4, "-0.3333"),
    ],
)
def test_rounded_decimal(value, digits, expected):
    assert _rounded_decimal(value, digits) == expected
