"""Bind the workstation coordinator's fresh kit execution copies to its process."""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

EXECUTION_COPY_PREFIXES = ("offline-source-", "bundle-recheck-")
_COPY_NAME = re.compile(r"(?:offline-source|bundle-recheck)-[A-Za-z0-9_]{8}")
_SCOPE: ContextVar[list[Path] | None] = ContextVar("fdai_execution_copy_scope", default=None)


def new_execution_copy(work_dir: Path, prefix: str) -> Path:
    """Create one fresh private execution-copy parent and register it with an open scope."""

    if prefix not in EXECUTION_COPY_PREFIXES:
        raise ValueError("deployment kit execution copy prefix is unsupported")
    parent = Path(tempfile.mkdtemp(prefix=prefix, dir=work_dir))
    scope = _SCOPE.get()
    if scope is not None:
        scope.append(parent)
    return parent


@contextmanager
def execution_copy_scope() -> Iterator[None]:
    """Remove the execution copies created inside this scope when it exits.

    Only the workstation coordinator opens a scope. Its copies are re-derivable from the
    operator-supplied signed kit and no retained record references them, so every exit removes
    them. The managed host opens no scope, because later steps of a run execute Terraform from
    its copy.
    """

    created: list[Path] = []
    token = _SCOPE.set(created)
    try:
        yield
    finally:
        _SCOPE.reset(token)
        remaining = [parent for parent in created if not _remove_execution_copy(parent)]
        if remaining:
            print(
                "fdaictl: warning: execution copies remain for manual removal: "
                + ", ".join(parent.name for parent in remaining),
                file=sys.stderr,
            )


def _remove_execution_copy(parent: Path) -> bool:
    if _COPY_NAME.fullmatch(parent.name) is None or parent.is_symlink():
        return False
    shutil.rmtree(parent, ignore_errors=True)
    return not (parent.exists() or parent.is_symlink())


__all__ = ["EXECUTION_COPY_PREFIXES", "execution_copy_scope", "new_execution_copy"]
