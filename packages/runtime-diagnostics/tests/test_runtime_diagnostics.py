from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import tracemalloc
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError
from fdai_runtime_diagnostics import probe as probe_module

from fdai_runtime_diagnostics import (
    DevelopmentDiagnosticServer,
    DevelopmentDiagnosticsConfig,
    RuntimeProbe,
    observe_stage,
    request_profile,
)

ROOT = Path(__file__).resolve().parents[3]
REVISION = "a" * 40
DIGEST = "b" * 64
RECEIPT = "sha256:" + ("d" * 64)
_ALLOCATIONS: list[bytearray] = []


def _environment(tmp_path: Path, **overrides: str) -> dict[str, str]:
    values = {
        "FDAI_DEVELOPMENT_DIAGNOSTICS": "1",
        "FDAI_EXECUTION_VENUE": "local",
        "FDAI_DEVELOPMENT_DIAGNOSTICS_SOURCE_REVISION": REVISION,
        "FDAI_DEVELOPMENT_DIAGNOSTICS_INPUT_DIGEST": DIGEST,
        "FDAI_DEVELOPMENT_DIAGNOSTICS_WORKTREE_DIGEST": hashlib.sha256(
            tmp_path.name.encode("utf-8")
        ).hexdigest(),
        "FDAI_DEVELOPMENT_DIAGNOSTICS_SOURCE_ROOT": str(ROOT),
        "FDAI_DEVELOPMENT_DIAGNOSTICS_SOCKET_DIR": str(ROOT / ".fdai" / "r"),
    }
    values.update(overrides)
    return values


def _config(tmp_path: Path) -> DevelopmentDiagnosticsConfig:
    config = DevelopmentDiagnosticsConfig.from_environment(
        "core-control-plane",
        RECEIPT,
        _environment(tmp_path),
    )
    assert config is not None
    return config


def _cleanup_socket(config: DevelopmentDiagnosticsConfig) -> None:
    config.socket_path.with_suffix(".lock").unlink(missing_ok=True)
    try:
        config.socket_path.parent.rmdir()
    except OSError:
        pass


def test_configuration_is_disabled_by_default_and_rejects_deployed(tmp_path: Path) -> None:
    assert DevelopmentDiagnosticsConfig.from_environment("core-control-plane", RECEIPT, {}) is None
    with pytest.raises(ValueError, match="local execution venue"):
        DevelopmentDiagnosticsConfig.from_environment(
            "core-control-plane",
            RECEIPT,
            _environment(tmp_path, FDAI_EXECUTION_VENUE="deployed"),
        )


def test_socket_name_is_short_and_bound_to_service_receipt(tmp_path: Path) -> None:
    first = _config(tmp_path)
    second = DevelopmentDiagnosticsConfig.from_environment(
        "operator-service",
        RECEIPT,
        _environment(tmp_path),
    )
    changed_receipt = DevelopmentDiagnosticsConfig.from_environment(
        "core-control-plane",
        "sha256:" + ("e" * 64),
        _environment(tmp_path),
    )
    changed_worktree = DevelopmentDiagnosticsConfig.from_environment(
        "core-control-plane",
        RECEIPT,
        _environment(
            tmp_path,
            FDAI_DEVELOPMENT_DIAGNOSTICS_WORKTREE_DIGEST="f" * 64,
        ),
    )

    assert second is not None and changed_receipt is not None and changed_worktree is not None
    assert re.fullmatch(r"[0-9a-f]{12}\.sock", first.socket_path.name)
    assert len(os.fsencode(first.socket_path)) <= 100
    assert (
        len(
            {
                first.socket_path,
                second.socket_path,
                changed_receipt.socket_path,
                changed_worktree.socket_path,
            }
        )
        == 4
    )


def test_direct_configuration_cannot_bypass_local_venue(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with pytest.raises(ValueError, match="local execution venue"):
        replace(config, execution_venue="deployed")  # type: ignore[arg-type]


async def test_snapshot_is_digest_bound_and_authority_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FDAI_DEVELOPMENT_DIAGNOSTICS", "1")
    observe_stage("conversation.route", 2.5)
    packet = await RuntimeProbe(_config(tmp_path)).capture()
    assert packet.capture_kind == "snapshot"
    assert packet.external_state_authority is False
    assert packet.execution_authority is False
    assert any(stage.name == "conversation.route" for stage in packet.stages)
    tampered = packet.model_dump(mode="json")
    tampered["measured_duration_ms"] += 1
    with pytest.raises(ValidationError, match="digest"):
        type(packet).model_validate(tampered)


async def test_profile_attributes_cpu_and_python_heap_to_repository(tmp_path: Path) -> None:
    probe = RuntimeProbe(_config(tmp_path))
    capture = asyncio.create_task(probe.capture(duration_ms=80, cpu=True, heap=True))
    await asyncio.sleep(0.01)
    _ALLOCATIONS.extend(bytearray(4096) for _ in range(64))
    sum(index * index for index in range(20_000))
    packet = await capture
    _ALLOCATIONS.clear()
    assert packet.capture_kind == "profile"
    assert packet.python_heap_after_bytes is not None
    assert packet.python_heap_peak_bytes is not None
    assert any(row.path.endswith("test_runtime_diagnostics.py") for row in packet.cpu_top)
    assert any(row.path.endswith("test_runtime_diagnostics.py") for row in packet.heap_top)
    assert all(row.path.endswith(".py") and not row.path.startswith(".") for row in packet.cpu_top)
    assert all(row.path.endswith(".py") and not row.path.startswith(".") for row in packet.heap_top)


async def test_profile_lag_excludes_capture_postprocessing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticks = iter((0, 1_000_000, 3_000_000, 103_000_000))
    monkeypatch.setattr(probe_module.time, "monotonic_ns", lambda: next(ticks))

    packet = await RuntimeProbe(_config(tmp_path)).capture(duration_ms=1, cpu=True)

    assert packet.measured_duration_ms == 103
    assert packet.event_loop_lag_ms == 1.0


async def test_probe_rejects_a_second_capture(tmp_path: Path) -> None:
    probe = RuntimeProbe(_config(tmp_path))
    first = asyncio.create_task(probe.capture(duration_ms=50, cpu=True))
    await asyncio.sleep(0)
    with pytest.raises(RuntimeError, match="already active"):
        await probe.capture(duration_ms=1, cpu=True)
    await first


async def test_cancelled_heap_capture_stops_owned_tracemalloc(tmp_path: Path) -> None:
    if tracemalloc.is_tracing():
        tracemalloc.stop()
    probe = RuntimeProbe(_config(tmp_path))
    capture = asyncio.create_task(probe.capture(duration_ms=1000, heap=True))
    await asyncio.sleep(0)
    capture.cancel()
    with pytest.raises(asyncio.CancelledError):
        await capture
    assert tracemalloc.is_tracing() is False


async def test_owner_only_socket_round_trip_and_cleanup(tmp_path: Path) -> None:
    config = _config(tmp_path)
    server = DevelopmentDiagnosticServer(config)
    await server.start()
    try:
        assert config.socket_path.stat().st_mode & 0o777 == 0o600
        packet = await request_profile(config.socket_path)
        assert packet.service_id == "core-control-plane"
    finally:
        await server.aclose()
        _cleanup_socket(config)
    assert not config.socket_path.exists()


async def test_socket_lock_prevents_a_second_owner(tmp_path: Path) -> None:
    config = _config(tmp_path)
    first = DevelopmentDiagnosticServer(config)
    second = DevelopmentDiagnosticServer(config)
    await first.start()
    try:
        with pytest.raises(RuntimeError, match="already owned"):
            await second.start()
        packet = await request_profile(config.socket_path)
        assert packet.service_id == "core-control-plane"
    finally:
        await first.aclose()
        _cleanup_socket(config)


async def test_socket_rejects_malformed_request(tmp_path: Path) -> None:
    config = _config(tmp_path)
    server = DevelopmentDiagnosticServer(config)
    await server.start()
    try:
        reader, writer = await asyncio.open_unix_connection(config.socket_path)
        writer.write(b'{"schema_version":"1.0.0","command":"unknown"}\n')
        await writer.drain()
        response = json.loads(await reader.readline())
        writer.close()
        await writer.wait_closed()
        assert response == {
            "status": "error",
            "reason": "development diagnostic command is unsupported",
        }
    finally:
        await server.aclose()
        _cleanup_socket(config)


def test_socket_root_must_stay_under_private_state(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escaped private local state"):
        DevelopmentDiagnosticsConfig.from_environment(
            "core-control-plane",
            RECEIPT,
            _environment(
                tmp_path,
                FDAI_DEVELOPMENT_DIAGNOSTICS_SOCKET_DIR=str(tmp_path),
            ),
        )


def test_test_environment_does_not_leak_diagnostic_configuration() -> None:
    assert "FDAI_DEVELOPMENT_DIAGNOSTICS" not in os.environ
