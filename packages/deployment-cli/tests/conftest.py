"""Shared isolation for deployment CLI tests."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _restore_process_umask() -> Iterator[None]:
    """Keep the one-shot host checkpoint umask from leaking into later tests.

    ``standalone_host.main`` sets an owner-only umask for its own process. Tests call it in
    process, so restore the previous mask after each test instead of letting it change file
    modes that unrelated tests create later in the same worker.
    """
    previous = os.umask(0o022)
    os.umask(previous)
    try:
        yield
    finally:
        os.umask(previous)


@pytest.fixture(autouse=True)
def _isolate_workstation_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep provision tests away from the real Azure CLI session and checkout key.

    Tests of the preflight itself call ``entitlement_preflight`` directly or restore
    the real functions on ``cli`` explicitly.
    """
    from fdai_deployment_cli import cli

    monkeypatch.setattr(cli, "select_entitlement_mode", lambda: "trial")
    monkeypatch.setattr(cli, "ensure_azure_session", lambda **_kwargs: None)
