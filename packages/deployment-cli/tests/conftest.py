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
