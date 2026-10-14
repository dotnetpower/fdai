"""The dry-run scenario end to end: the real Hub command line, Hub API, and agent processes."""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest
from lifecycle.demo import __main__ as demo_cli
from lifecycle.demo.catalog import Layout
from lifecycle.demo.scenario import Scenario

_CREDENTIAL_PREFIXES = ("AZURE_", "ARM_", "MSI_", "IDENTITY_")


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


@pytest.fixture(autouse=True)
def child_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Child processes import what this test imports, and see no Azure credential."""

    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(path for path in sys.path if path))
    for name in [n for n in os.environ if n.startswith(_CREDENTIAL_PREFIXES)]:
        monkeypatch.delenv(name)


def test_dry_run_scenario_admits_the_first_two_releases(tmp_path: Path) -> None:
    lines: list[str] = []

    Scenario(layout=Layout(tmp_path / "demo"), port=_free_port(), say=lines.append).run()

    assert "reports for demo-00000001: ['dry-run-admitted']" in lines
    assert "reports for demo-00000002: ['dry-run-admitted']" in lines
    assert lines[-1].endswith("the 1.2.0 rollback needs --apply.")


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["run", "--apply"], "--apply needs --kube-context and --namespace"),
        (
            ["run", "--apply", "--kube-context", "kind-demo", "--namespace", "kube-system"],
            "dedicated demo namespace",
        ),
    ],
)
def test_apply_needs_a_context_and_a_dedicated_namespace(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    message: str,
) -> None:
    for name in (demo_cli.KUBE_CONTEXT_ENV, demo_cli.NAMESPACE_ENV):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(SystemExit):
        demo_cli.main(argv)

    assert message in capsys.readouterr().err
