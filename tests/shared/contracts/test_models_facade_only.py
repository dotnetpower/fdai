"""Facade-only import guard for the split contract-models package.

After the G-4 split, callers MUST continue to import from
``fdai.shared.contracts.models`` (the facade), not from a submodule like
``fdai.shared.contracts.models.event`` or
``fdai.shared.contracts.models.ontology``. If a submodule import creeps
in, the facade becomes cosmetic and a future re-organisation (renaming a
submodule, merging two, splitting one further) can silently break
callsites.

Two exceptions:

- The submodule files themselves (they use relative imports).
- The regression tests under ``tests/shared/contracts/`` are allowed to
  poke at the package internals for structural drift guards.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MODELS_PATH = _REPO_ROOT / "src" / "fdai" / "shared" / "contracts" / "models"

# Match either 'from fdai.shared.contracts.models.<X>' or
# 'import fdai.shared.contracts.models.<X>' where X is a submodule name.
_SUBMODULE_IMPORT = re.compile(
    r"(?:from|import)\s+fdai\.shared\.contracts\.models\.[a-zA-Z_][a-zA-Z0-9_]*"
)


def _iter_python_files() -> list[Path]:
    tracked: list[Path] = []
    for path in _REPO_ROOT.glob("src/**/*.py"):
        # Skip the models package itself - relative imports are the intended
        # pattern there.
        if _MODELS_PATH in path.parents or path.parent == _MODELS_PATH:
            continue
        tracked.append(path)
    for path in _REPO_ROOT.glob("tests/**/*.py"):
        # Allow tests under shared/contracts/ - they deliberately introspect
        # the split.
        if "shared/contracts" in str(path.relative_to(_REPO_ROOT)).replace("\\", "/"):
            continue
        tracked.append(path)
    return tracked


def test_no_caller_reaches_into_submodule() -> None:
    offenders: list[tuple[str, str]] = []
    for path in _iter_python_files():
        try:
            body = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in body.splitlines():
            if _SUBMODULE_IMPORT.search(line):
                offenders.append((str(path.relative_to(_REPO_ROOT)), line.strip()))

    if offenders:
        rendered = "\n  ".join(f"{p}: {line}" for p, line in offenders)
        pytest.fail(
            "Callers are reaching into models submodules directly, which "
            "defeats the G-4 facade split. Import from "
            "'fdai.shared.contracts.models' instead:\n  " + rendered
        )
