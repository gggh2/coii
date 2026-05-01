"""Result pattern — activities return Ok(value) | Err(code, message), never raise.

Controller checks .ok and maps to HTTP status. Activity catches exceptions from
service clients (Linear API, file I/O) and converts them to Err.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Ok(Generic[T]):
    value: T
    ok: bool = True


@dataclass(frozen=True)
class Err:
    code: str
    message: str
    ok: bool = False


Result = Ok[T] | Err
