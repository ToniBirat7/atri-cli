"""Request-scoped logging context for structured observability."""

from contextvars import ContextVar
from typing import Optional


REQUEST_ID: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
TURN_ID: ContextVar[Optional[int]] = ContextVar("turn_id", default=None)


def set_request_id(value: Optional[str]) -> None:
    REQUEST_ID.set(value)


def get_request_id() -> Optional[str]:
    return REQUEST_ID.get()


def set_turn_id(value: Optional[int]) -> None:
    TURN_ID.set(value)


def get_turn_id() -> Optional[int]:
    return TURN_ID.get()
