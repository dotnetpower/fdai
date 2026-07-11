"""Structural drift guards for the G-7 agents/_framework split.

The 15 pantheon members MUST stay flat at the top level (they are a
first-class charter catalog); everything else MUST live under
``_framework/``. These tests catch drift in either direction.

Tracker: #14, issue #21.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import fdai.agents as agents_pkg
import fdai.agents._framework as framework_pkg

_REPO_ROOT = Path(__file__).resolve().parents[2]
_AGENTS_DIR = _REPO_ROOT / "src" / "fdai" / "agents"
_FRAMEWORK_DIR = _AGENTS_DIR / "_framework"

_PANTHEON_15 = frozenset(
    {
        "odin",
        "thor",
        "forseti",
        "huginn",
        "heimdall",
        "var",
        "vidar",
        "bragi",
        "saga",
        "mimir",
        "muninn",
        "norns",
        "njord",
        "freyr",
        "loki",
    }
)


# ---------------------------------------------------------------------------
# H1: layout - flat pantheon at the top, framework in _framework/
# ---------------------------------------------------------------------------


def test_top_level_is_exactly_pantheon_plus_init() -> None:
    top_pyfiles = sorted(
        p.stem for p in _AGENTS_DIR.glob("*.py") if p.name != "__init__.py"
    )
    assert set(top_pyfiles) == _PANTHEON_15, (
        f"Top-level agents/*.py must be exactly the 15 pantheon members. "
        f"Extra: {set(top_pyfiles) - _PANTHEON_15}, "
        f"missing: {_PANTHEON_15 - set(top_pyfiles)}. Framework helpers "
        "belong under agents/_framework/."
    )


def test_framework_subpackage_exists() -> None:
    assert _FRAMEWORK_DIR.is_dir(), "_framework/ subpackage missing"
    assert (_FRAMEWORK_DIR / "__init__.py").is_file(), (
        "_framework/__init__.py missing"
    )


def test_pantheon_count_is_15_exactly() -> None:
    # Sanity check against the AgentSpec catalog itself. Names are
    # title-case in PANTHEON_NAMES (spec-facing); the on-disk module
    # names are lowercase (Python filesystem convention).
    assert len(agents_pkg.PANTHEON_NAMES) == 15
    assert {name.lower() for name in agents_pkg.PANTHEON_NAMES} == _PANTHEON_15


# ---------------------------------------------------------------------------
# H2: import boundary - external callers use fdai.agents (the facade),
# never fdai.agents._framework.X. The underscore prefix means "not for
# external consumption"; forks that reach in break silently on renames.
# ---------------------------------------------------------------------------


_FRAMEWORK_IMPORT = re.compile(
    r"(?:from|import)\s+fdai\.agents\._framework\.[a-zA-Z_][a-zA-Z0-9_]*"
)


def _iter_external_python_files() -> list[Path]:
    files: list[Path] = []
    # src/ except src/fdai/agents/
    for path in _REPO_ROOT.glob("src/**/*.py"):
        if _AGENTS_DIR in path.parents or path.parent == _AGENTS_DIR:
            continue
        files.append(path)
    # tests/ except tests/agents/ (which legitimately introspects the split
    # for these very drift guards).
    for path in _REPO_ROOT.glob("tests/**/*.py"):
        rel = str(path.relative_to(_REPO_ROOT)).replace("\\", "/")
        if rel.startswith("tests/agents/"):
            continue
        files.append(path)
    return files


def test_no_external_caller_reaches_into_framework() -> None:
    offenders: list[tuple[str, str]] = []
    for path in _iter_external_python_files():
        try:
            body = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in body.splitlines():
            if _FRAMEWORK_IMPORT.search(line):
                offenders.append(
                    (str(path.relative_to(_REPO_ROOT)), line.strip())
                )
    if offenders:
        rendered = "\n  ".join(f"{p}: {line}" for p, line in offenders)
        pytest.fail(
            "External callers are reaching into agents/_framework/, which "
            "defeats the G-7 facade split. Import from 'fdai.agents' "
            "instead:\n  " + rendered
        )


# ---------------------------------------------------------------------------
# H3: pantheon members MAY reach into _framework/ (they need Agent, the
# spec, adapters, etc.). But they MUST NOT import each other - the
# pantheon is a flat catalog and cross-member imports collapse the
# arbitration model. Verified indirectly: no top-level agent file
# imports 'from fdai.agents.<peer_name>' or 'from .<peer_name>'.
# ---------------------------------------------------------------------------


def test_no_cross_pantheon_imports() -> None:
    peer_re = re.compile(
        r"^\s*(?:from|import)\s+(?:fdai\.agents|\.)(?:\.|\s+)(?P<n>[a-z_]+)",
        re.M,
    )
    offenders: list[tuple[str, str, str]] = []
    for name in _PANTHEON_15:
        path = _AGENTS_DIR / f"{name}.py"
        body = path.read_text(encoding="utf-8")
        for match in peer_re.finditer(body):
            imported = match.group("n")
            if imported in _PANTHEON_15 and imported != name:
                offenders.append((name, imported, match.group(0).strip()))
    assert not offenders, (
        "Pantheon members must not import each other; use the bus / "
        "typed topics for cross-agent communication. Offenders: "
        + str(offenders)
    )


# ---------------------------------------------------------------------------
# H5: file LOC ceiling inside _framework/ (own drift guard - _framework
# is a growth area; keep it split).
# ---------------------------------------------------------------------------


def test_no_framework_file_exceeds_800_loc() -> None:
    over = []
    for path in sorted(_FRAMEWORK_DIR.glob("*.py")):
        loc = path.read_text().count("\n")
        if loc > 800:
            over.append((path.name, loc))
    assert not over, (
        f"agents/_framework files exceed the 800-LOC hard ceiling: {over}. "
        "Split further."
    )


# ---------------------------------------------------------------------------
# H4: framework __init__ docstring pins the design intent so a well-meaning
# refactor cannot silently rewrite it away.
# ---------------------------------------------------------------------------


def test_framework_init_docstring_pins_intent() -> None:
    doc = (framework_pkg.__doc__ or "").lower()
    for anchor in (
        "framework",
        "pantheon",
        "not for external consumption",
        "underscore",
    ):
        assert anchor in doc, (
            f"agents/_framework/__init__.py docstring lost the anchor "
            f"'{anchor}' - the G-7 intent is drifting."
        )


# ---------------------------------------------------------------------------
# H10: no _framework file may shadow a pantheon member's name. A future
# helper named 'thor.py' under _framework/ (however tempting - "Thor's
# retry helper") would confuse maintainers into thinking there are two
# Thors and would break the top-level-is-pantheon invariant if anyone
# ever relocates it. Reserve those 15 names at the framework layer too.
# ---------------------------------------------------------------------------


def test_no_framework_file_shadows_a_pantheon_member() -> None:
    framework_stems = {
        p.stem
        for p in _FRAMEWORK_DIR.glob("*.py")
        if p.name != "__init__.py"
    }
    collisions = framework_stems & _PANTHEON_15
    assert not collisions, (
        f"agents/_framework/ contains file(s) that shadow a pantheon "
        f"member name: {sorted(collisions)}. Pick a different name for "
        "the helper (e.g. 'thor_retry.py' rather than 'thor.py') so a "
        "future refactor cannot promote it to the top level and create "
        "two agents with the same name."
    )


# ---------------------------------------------------------------------------
# H11: private submodule is not exported from the facade. Exposing
# fdai.agents._framework as a public name in __all__ would defeat the
# "reach through the facade" rule; the wildcard import would then
# leak internals into every 'from fdai.agents import *' consumer.
# ---------------------------------------------------------------------------


def test_framework_is_not_in_facade_all() -> None:
    exported = set(agents_pkg.__all__)
    assert "_framework" not in exported
    # Sanity: no re-export of the module object itself.
    assert not any(
        name.startswith("_framework") for name in exported
    )

