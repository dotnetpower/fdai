from __future__ import annotations

from pathlib import Path


def test_scanner_entrypoint_maps_the_supervised_worker_command() -> None:
    root = Path(__file__).resolve().parents[4]
    entrypoint = (
        root / "services/core-control-plane/docker/code-security-scanner-entrypoint.sh"
    ).read_text(encoding="utf-8")

    assert "serve-workers)\n    shift\n    run_with_scanners serve-workers" in entrypoint
    assert "serve-workers [ARGS...]" in entrypoint
