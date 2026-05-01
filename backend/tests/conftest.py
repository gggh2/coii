"""Shared test fixtures.

Every test runs against an isolated, empty ``~/.coii/`` so:
  * the developer's real ``~/.coii/config.json`` doesn't leak in
  * the developer's real ``services/coii/.env.local_deploy`` doesn't leak in
  * each test starts with a fresh ``app.config`` singleton

Tests that *want* a populated config write into the per-test tmp dir
explicitly (see test_config.py / test_agent_loader.py).
"""

from __future__ import annotations

import pytest

from app import config


@pytest.fixture(autouse=True)
def _isolate_coii_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("COII_ROOT", str(tmp_path / "coii_root"))
    monkeypatch.setenv("COII_CONFIG_PATH", str(tmp_path / "coii_root" / "config.json"))
    monkeypatch.setenv("COII_DISABLE_DOTENV", "1")
    config._singleton = None
    yield
    config._singleton = None


@pytest.fixture
def coii_dir(tmp_path):
    """Directory the autouse fixture's COII_ROOT points at."""
    return tmp_path / "coii_root"
