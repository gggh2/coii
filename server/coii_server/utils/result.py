from dataclasses import dataclass, field
from typing import Any, Optional, Generic, TypeVar

T = TypeVar("T")


@dataclass
class Ok(Generic[T]):
    value: T
    ok: bool = field(default=True, init=False)


@dataclass
class Err:
    code: str
    message: str
    ok: bool = field(default=False, init=False)


Result = Ok | Err
