"""Money value object — Decimal helpers for financial calculations.

Every monetary column in the ERP is NUMERIC(19,4). These helpers guarantee
all amounts flowing through the system stay quantized to 4 decimal places
and never touch floats.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Iterable, Union

# 4 decimal places — matches NUMERIC(19,4) across all ERP tables.
_MONEY_PLACES: int = 4
_MONEY_EXP = Decimal("0.0001")  # 10^-4

# Rounding tolerance for balancing entries — matches ERPNext's 0.5 allowance
# (5 / 10^precision = 5 / 10^4 = 0.0005 for journal entries).
ROUNDING_TOLERANCE: Decimal = Decimal("0.0005")


def money(amount: Union[str, int, float, Decimal], places: int = _MONEY_PLACES) -> Decimal:
    """Quantize *amount* to *places* decimal places using ROUND_HALF_UP.

    >>> money("100.12345")
    Decimal('100.1235')
    >>> money(100)
    Decimal('100.0000')
    """
    try:
        d = Decimal(str(amount))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Cannot convert {amount!r} to a monetary Decimal") from exc
    return d.quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP)


def money_zero(places: int = _MONEY_PLACES) -> Decimal:
    """Return Decimal zero quantized to *places* places."""
    return Decimal("0").quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP)


def money_sum(iterable: Iterable[Decimal]) -> Decimal:
    """Sum an iterable of Decimals and return a quantized result.

    Safer than sum(...) because every term is already a Decimal and the
    result is quantized back to 4 places.
    """
    total = Decimal("0")
    for item in iterable:
        total += item
    return money(total)


def money_round(d: Decimal, places: int = _MONEY_PLACES) -> Decimal:
    """Re-quantize an existing Decimal to *places*."""
    return d.quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP)


def fx_rate(rate: Union[str, int, float, Decimal]) -> Decimal:
    """Quantize an FX rate to 8 decimal places (matches NUMERIC(19,8))."""
    return Decimal(str(rate)).quantize(
        Decimal("0.00000001"), rounding=ROUND_HALF_UP
    )


def qty(quantity: Union[str, int, float, Decimal]) -> Decimal:
    """Quantize a quantity to 2 decimal places (matches NUMERIC(12,2))."""
    return Decimal(str(quantity)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
