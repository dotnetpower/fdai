"""Scenario: no write. The Lifecycle I0 agent performs no Kubernetes or Azure write.

Two independent proofs: no agent module imports a Kubernetes, Azure, or process-spawning
client, and a full poll in a fresh interpreter never loads one.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "fdai_lifecycle_agent"
FORBIDDEN_ROOTS = ("kubernetes", "azure", "subprocess", "msrest", "msal")


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "__import__"
        ):
            modules.add("<dynamic>")
    return modules


def test_agent_sources_import_no_kubernetes_azure_or_process_client() -> None:
    sources = sorted(PACKAGE_ROOT.glob("*.py"))
    assert sources

    for source in sources:
        modules = _imported_modules(source)
        assert "<dynamic>" not in modules, source.name
        assert "importlib" not in modules, source.name
        offending = {module for module in modules if module.split(".")[0] in FORBIDDEN_ROOTS}
        assert offending == set(), source.name


def test_network_client_is_confined_to_the_hub_client() -> None:
    users = {
        source.name
        for source in PACKAGE_ROOT.glob("*.py")
        if any(module.split(".")[0] == "httpx" for module in _imported_modules(source))
    }

    assert users == {"hub_client.py"}


_POLL_IN_FRESH_INTERPRETER = """
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import conftest
from fdai_lifecycle_agent import agent, cli

harness = conftest.Harness(Path(sys.argv[2]))
harness.serve(harness.plan())
result = harness.poll()
assert result.outcome == "dry-run-admitted", result
loaded = sorted(
    name for name in sys.modules
    if name.split(".")[0] in {"kubernetes", "azure", "msrest", "msal"}
)
print(",".join(loaded))
"""


def test_full_poll_loads_no_kubernetes_or_azure_client(tmp_path: Path) -> None:
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and test-owned script
        [
            sys.executable,
            "-c",
            _POLL_IN_FRESH_INTERPRETER,
            str(Path(__file__).resolve().parent),
            str(tmp_path / "state"),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        # Reuse the test interpreter's import path; the root suite resolves packages through it.
        env={**os.environ, "PYTHONPATH": os.pathsep.join(path for path in sys.path if path)},
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == ""
