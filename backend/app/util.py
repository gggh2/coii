"""Shared helpers."""

from __future__ import annotations

import os
from pathlib import Path


def coii_root() -> Path:
    """Runtime root (~/.coii/): config.json, agents/, workflows/, tickets/.

    On a fresh install, `coii init` seeds this from the packaged
    defaults at app/default/. After that the operator and the agents
    themselves both read and write here.

    Override via COII_ROOT for tests / non-default deploy.
    """
    raw = os.getenv("COII_ROOT", "~/.coii")
    return Path(os.path.expanduser(raw)).resolve()


def defaults_root() -> Path:
    """Path to the packaged factory defaults that ship inside the wheel.

    Used by `coii init` to seed `coii_root()` on first install.
    Not consulted at runtime by the loaders.
    """
    return (Path(__file__).parent / "default").resolve()


def env_int(name: str, default: int, minimum: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        v = int(raw)
    except ValueError:
        return default
    if minimum is not None and v < minimum:
        return minimum
    return v
