"""Repository guard: no raw chaos mutation path outside the governed adapter.

Live chaos runs only through ``GovernedChaosExecutionAdapter``. Scripts and
services must not construct ``FaultInjectionHarness``, call an injector's
``inject``/``stop`` contract, or drive ``GovernedChaosRunner.run_enforce``
themselves. Each allowance below names the only module that may do so and why.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHAOS = "services/core-control-plane/src/fdai/core/chaos"
_DELIVERY = "services/core-control-plane/src/fdai/delivery/chaos"

_HARNESS_IMPORTS = {
    f"{_CHAOS}/__init__.py",  # package re-export
    f"{_CHAOS}/runner.py",  # receives the harness it is handed; never builds one
    f"{_DELIVERY}/governed.py",  # builds the enforce harness only for GovernedChaosRunner
    f"{_DELIVERY}/tool.py",  # builds a shadow-only harness; enforce delegates first
}
_HARNESS_CONSTRUCTION = {f"{_DELIVERY}/governed.py", f"{_DELIVERY}/tool.py"}
_INJECTOR_CALLS = {
    f"{_CHAOS}/harness.py",  # the harness owns inject, hold, and rollback
    f"{_DELIVERY}/mutation_scope.py",  # ScopedInjector delegates to its bound injector
}
_RUN_ENFORCE_CALLS = {f"{_DELIVERY}/governed.py"}
_TOKENS = ("FaultInjectionHarness", "fdai.core.chaos.harness", ".inject(", ".stop(", "run_enforce")


def _python_sources() -> list[str]:
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.py"],  # noqa: S607 - repository test invokes Git from PATH.
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return sorted(
        {path for path in listed if "/tests/" not in path and not path.startswith("tests/")}
    )


def _empty() -> dict[str, set[str]]:
    return {
        "harness_import": set(),
        "harness_construction": set(),
        "injector_call": set(),
        "run_enforce": set(),
    }


def _scan(relative: str, source: str, found: dict[str, set[str]]) -> None:
    if not any(token in source for token in _TOKENS):
        return
    for node in ast.walk(ast.parse(source, filename=relative)):
        if isinstance(node, ast.ImportFrom) and (
            node.module == "fdai.core.chaos.harness"
            or any(alias.name == "FaultInjectionHarness" for alias in node.names)
        ):
            found["harness_import"].add(relative)
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Name):
            name = function.id
        elif isinstance(function, ast.Attribute):
            name = function.attr
        else:
            continue
        if name == "FaultInjectionHarness":
            found["harness_construction"].add(relative)
        elif name in {"inject", "stop"} and any(kw.arg == "target" for kw in node.keywords):
            found["injector_call"].add(relative)
        elif name == "run_enforce":
            found["run_enforce"].add(relative)


def _uses() -> dict[str, set[str]]:
    found = _empty()
    for relative in _python_sources():
        path = _REPO_ROOT / relative
        if path.is_file():
            _scan(relative, path.read_text(encoding="utf-8"), found)
    return found


def test_no_raw_chaos_mutation_path_outside_the_governed_adapter() -> None:
    uses = _uses()

    assert uses["harness_import"] <= _HARNESS_IMPORTS, sorted(
        uses["harness_import"] - _HARNESS_IMPORTS
    )
    assert uses["harness_construction"] <= _HARNESS_CONSTRUCTION, sorted(
        uses["harness_construction"] - _HARNESS_CONSTRUCTION
    )
    assert uses["injector_call"] <= _INJECTOR_CALLS, sorted(uses["injector_call"] - _INJECTOR_CALLS)
    assert uses["run_enforce"] <= _RUN_ENFORCE_CALLS, sorted(
        uses["run_enforce"] - _RUN_ENFORCE_CALLS
    )
    assert not any(path.startswith("scripts/") for paths in uses.values() for path in paths), (
        "a script builds or drives a raw chaos mutation path"
    )


def test_guard_flags_every_raw_chaos_construct() -> None:
    found = _empty()
    _scan(
        "scripts/raw_driver.py",
        "from fdai.core.chaos.harness import FaultInjectionHarness as Harness\n"
        "from fdai.core.chaos import FaultInjectionHarness\n"
        "async def main(injector, scenario, runner):\n"
        "    await FaultInjectionHarness(injectors=[injector]).run(scenario, approved_targets=[])\n"
        "    await Harness(injectors=[injector]).run(scenario, approved_targets=[])\n"
        "    await injector.inject(target='a', params={})\n"
        "    await injector.stop(target='a')\n"
        "    await runner.run_enforce(run_id='r')\n",
        found,
    )

    assert all(paths == {"scripts/raw_driver.py"} for paths in found.values()), found
