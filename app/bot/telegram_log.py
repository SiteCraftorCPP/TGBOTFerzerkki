"""Детали ошибок Telegram API для логов."""

from __future__ import annotations


def telegram_error_details(exc: BaseException) -> str:
    bits = [f"{type(exc).__name__}: {exc}"]
    for name in ("method", "message"):
        v = getattr(exc, name, None)
        if v is not None and v != str(exc):
            bits.append(f"{name}={v!r}")
    return " | ".join(bits)
