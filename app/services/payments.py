from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.services.errors import PaymentStateError

_AMOUNT = re.compile(r"^[0-9]{1,7}(?:[.,][0-9]{1,2})?$")
_MAX_TOPUP_KOPECKS = 100_000_000


def parse_rubles(value: str, minimum_kopecks: int) -> int:
    normalized = value.strip().replace(",", ".")
    if not _AMOUNT.fullmatch(normalized):
        raise PaymentStateError("Введите сумму числом, например 100 или 100.50.")
    try:
        kopecks = int((Decimal(normalized) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError) as error:
        raise PaymentStateError("Некорректная сумма пополнения.") from error
    if kopecks < minimum_kopecks:
        raise PaymentStateError(f"Минимальная сумма — {format_rubles(minimum_kopecks)}.")
    if kopecks > _MAX_TOPUP_KOPECKS:
        raise PaymentStateError("Сумма пополнения слишком большая.")
    return kopecks


def format_rubles(kopecks: int) -> str:
    rubles, remainder = divmod(abs(kopecks), 100)
    sign = "-" if kopecks < 0 else ""
    if remainder:
        return f"{sign}{rubles}.{remainder:02d} ₽"
    return f"{sign}{rubles} ₽"
