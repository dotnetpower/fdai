from __future__ import annotations

import importlib.util
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest
from fdai_runtime_diagnostics import (
    DevelopmentDiagnosticsConfig,
    DevelopmentDiagnosticServer,
)
from fdai_runtime_diagnostics.models import DevelopmentProfilePacket, ProcessSnapshot
from jsonschema import Draft202012Validator

ROOT = Path(__file__).parents[3]
SCRIPT = ROOT / "scripts" / "automation" / "dev-discuss.py"
REVISION = "a" * 40
INPUT_DIGEST = "b" * 64
WORKTREE_DIGEST = "c" * 64
RECEIPT = "sha256:" + ("d" * 64)


def test_evaluation_receipt_matches_schema() -> None:
    schema = json.loads(
        (ROOT / "config/development-diagnostics-evaluation.schema.json").read_text(encoding="utf-8")
    )
    evidence = json.loads(
        (ROOT / "config/development-diagnostics-evaluation.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(evidence)
    assert [row["round"] for row in evidence["rounds"]] == list(range(1, 21))


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("dev_discuss_test_module", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _snapshot() -> ProcessSnapshot:
    return ProcessSnapshot(
        cpu_user_ms=1,
        cpu_system_ms=1,
        rss_bytes=1024,
        vms_bytes=2048,
        peak_rss_bytes=1024,
        thread_count=1,
        open_fd_count=1,
        gc_generation_counts=(0, 0, 0),
        gc_collections=0,
    )


def _profile() -> DevelopmentProfilePacket:
    now = datetime.now(UTC)
    return DevelopmentProfilePacket.build(
        schema_version="1.0.0",
        profile_id=str(uuid.uuid4()),
        service_id="core-control-plane",
        capture_kind="snapshot",
        source_revision=REVISION,
        service_input_digest=INPUT_DIGEST,
        worktree_digest=WORKTREE_DIGEST,
        runtime_scope_receipt_digest=RECEIPT,
        started_at=now,
        completed_at=now,
        requested_duration_ms=0,
        measured_duration_ms=0,
        event_loop_lag_ms=0,
        before=_snapshot(),
        after=_snapshot(),
        stages=(),
        cpu_top=(),
        heap_top=(),
        python_heap_before_bytes=None,
        python_heap_after_bytes=None,
        python_heap_peak_bytes=None,
        untracked_memory_bytes=None,
        limitations=(),
        complete=True,
        external_state_authority=False,
        execution_authority=False,
    )


def test_private_json_rejects_non_owner_input(tmp_path: Path) -> None:
    module = _load()
    path = tmp_path / "packet.json"
    path.write_text("{}\n", encoding="utf-8")
    path.chmod(0o644)
    with pytest.raises(ValueError, match="owner-only"):
        module._read_private_json(path)


def test_private_json_rejects_symlink_input(tmp_path: Path) -> None:
    module = _load()
    target = tmp_path / "target.json"
    target.write_text("{}\n", encoding="utf-8")
    target.chmod(0o600)
    path = tmp_path / "packet.json"
    path.symlink_to(target)
    with pytest.raises(OSError):
        module._read_private_json(path)


def test_copilot_review_import_is_digest_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    monkeypatch.setattr(module, "_git_revision", lambda _root: REVISION)
    monkeypatch.setattr(module, "_worktree_digest", lambda _root: WORKTREE_DIGEST)
    packet = module._review_packet(tmp_path, _profile(), "Where is the current bottleneck?")
    packet_path = tmp_path / "packet.json"
    result_path = tmp_path / "result.json"
    module._write_private_json(packet_path, packet)
    module._write_private_json(
        result_path,
        {
            "schema_version": "1.0.0",
            "review_id": packet["review_id"],
            "review_digest": packet["review_digest"],
            "packet_digest": packet["profile_packet"]["packet_digest"],
            "severity": "low",
            "diagnosis": "No measured regression in the bounded snapshot.",
            "code_refs": ["scripts/automation/dev-discuss.py:1"],
        },
    )

    record = module._import_review(tmp_path, packet_path, result_path)

    assert record["merge_authority"] is False
    assert record["execution_authority"] is False
    ledger = tmp_path / ".fdai" / "dev-discuss" / "reviews.jsonl"
    assert json.loads(ledger.read_text(encoding="utf-8"))["review_id"] == packet["review_id"]
    assert ledger.stat().st_mode & 0o077 == 0


def test_copilot_review_rejects_workspace_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    monkeypatch.setattr(module, "_git_revision", lambda _root: REVISION)
    monkeypatch.setattr(module, "_worktree_digest", lambda _root: WORKTREE_DIGEST)
    packet = module._review_packet(tmp_path, _profile(), "Explain memory growth.")
    packet_path = tmp_path / "packet.json"
    result_path = tmp_path / "result.json"
    module._write_private_json(packet_path, packet)
    module._write_private_json(result_path, {})
    monkeypatch.setattr(module, "_worktree_digest", lambda _root: "e" * 64)
    with pytest.raises(ValueError, match="workspace digest changed"):
        module._import_review(tmp_path, packet_path, result_path)


async def test_capture_accepts_one_exact_matching_runtime_packet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    short_root = Path(tempfile.mkdtemp(prefix="fdai-dd-"))
    socket_dir = short_root / ".fdai" / "runtime-diagnostics"
    config = DevelopmentDiagnosticsConfig(
        service_id="core-control-plane",
        execution_venue="local",
        socket_path=socket_dir / "core-control-plane.sock",
        source_root=short_root,
        source_revision=REVISION,
        service_input_digest=INPUT_DIGEST,
        worktree_digest=WORKTREE_DIGEST,
        runtime_scope_receipt_digest=RECEIPT,
    )
    server = DevelopmentDiagnosticServer(config)
    monkeypatch.setattr(module, "_git_revision", lambda _root: REVISION)
    monkeypatch.setattr(module, "_service_input_digest", lambda _root, _service: INPUT_DIGEST)
    await server.start()
    try:
        packet = await module._capture(
            short_root,
            service="core-control-plane",
            duration_ms=0,
            cpu=True,
            heap=True,
        )
        monkeypatch.setattr(
            module,
            "_service_input_digest",
            lambda _root, _service: "e" * 64,
        )
        with pytest.raises(ValueError, match="service inputs do not match"):
            await module._capture(
                short_root,
                service="core-control-plane",
                duration_ms=0,
                cpu=True,
                heap=True,
            )
    finally:
        await server.aclose()
        shutil.rmtree(short_root)
    assert packet.service_id == "core-control-plane"
    assert packet.packet_digest.startswith("sha256:")


async def test_status_rejects_a_stale_socket_file(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load()
    short_root = Path(tempfile.mkdtemp(prefix="fdai-dd-status-"))
    socket_dir = short_root / ".fdai" / "runtime-diagnostics"
    socket_dir.mkdir(parents=True)
    stale_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale_socket.bind(str(socket_dir / "operator-service.sock"))
    stale_socket.close()

    try:
        result = await module._status(short_root)
    finally:
        shutil.rmtree(short_root)

    assert result == 1
    assert json.loads(capsys.readouterr().out) == {
        "core-control-plane": False,
        "operator-service": False,
    }


async def test_status_accepts_a_live_diagnostic_server(
    capsys: pytest.CaptureFixture[str],
) -> None:
    short_root = Path(tempfile.mkdtemp(prefix="fdai-dd-status-"))
    socket_dir = short_root / ".fdai" / "runtime-diagnostics"
    config = DevelopmentDiagnosticsConfig(
        service_id="core-control-plane",
        execution_venue="local",
        socket_path=socket_dir / "core-control-plane.sock",
        source_root=short_root,
        source_revision=REVISION,
        service_input_digest=INPUT_DIGEST,
        worktree_digest=WORKTREE_DIGEST,
        runtime_scope_receipt_digest=RECEIPT,
    )
    server = DevelopmentDiagnosticServer(config)
    await server.start()
    try:
        result = await _load()._status(short_root)
    finally:
        await server.aclose()
        shutil.rmtree(short_root)

    assert result == 0
    assert json.loads(capsys.readouterr().out) == {
        "core-control-plane": True,
        "operator-service": False,
    }


def test_private_writer_uses_atomic_owner_only_file(tmp_path: Path) -> None:
    module = _load()
    path = tmp_path / "packet.json"
    module._write_private_json(path, {"ok": True})
    assert json.loads(path.read_text(encoding="utf-8")) == {"ok": True}
    assert path.stat().st_mode & 0o077 == 0
    assert not any(candidate.name.startswith(".packet.json.") for candidate in tmp_path.iterdir())


def test_copilot_import_rejects_a_missing_profile_packet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    monkeypatch.setattr(module, "_git_revision", lambda _root: REVISION)
    monkeypatch.setattr(module, "_worktree_digest", lambda _root: WORKTREE_DIGEST)
    packet = module._review_packet(tmp_path, _profile(), "Explain the current bottleneck.")
    packet["profile_packet"] = None
    body = {key: value for key, value in packet.items() if key != "review_digest"}
    packet["review_digest"] = module._digest(body)
    packet_path = tmp_path / "packet.json"
    result_path = tmp_path / "result.json"
    module._write_private_json(packet_path, packet)
    module._write_private_json(result_path, {})
    with pytest.raises(ValueError, match="profile packet is missing"):
        module._import_review(tmp_path, packet_path, result_path)


def test_review_ledger_rotates_before_exceeding_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    monkeypatch.setattr(module, "MAX_LEDGER_BYTES", 120)
    ledger = tmp_path / "reviews.jsonl"
    module._append_private_jsonl(ledger, {"record": "a" * 70})
    module._append_private_jsonl(ledger, {"record": "b" * 70})
    rotated = ledger.with_suffix(".jsonl.1")
    assert rotated.is_file()
    assert "a" * 70 in rotated.read_text(encoding="utf-8")
    assert "b" * 70 in ledger.read_text(encoding="utf-8")
    assert ledger.stat().st_mode & 0o077 == 0
    assert rotated.stat().st_mode & 0o077 == 0


def test_review_ledger_rejects_symlink_inside_lock(tmp_path: Path) -> None:
    module = _load()
    target = tmp_path / "target.jsonl"
    target.write_text("", encoding="utf-8")
    target.chmod(0o600)
    ledger = tmp_path / "reviews.jsonl"
    ledger.symlink_to(target)
    with pytest.raises(ValueError, match="cannot use a symlink"):
        module._append_private_jsonl(ledger, {"record": "blocked"})


def test_review_ledger_rotation_serializes_concurrent_imports(tmp_path: Path) -> None:
    ledger = tmp_path / "reviews.jsonl"
    worker_code = """
import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("dev_discuss_worker", sys.argv[1])
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
module.MAX_LEDGER_BYTES = 10_000
for index in range(30):
    prefix = sys.argv[3]
    module._append_private_jsonl(
        Path(sys.argv[2]),
        {"id": f"{prefix}-{index}", "diagnosis": prefix * 40},
    )
"""
    workers = [
        subprocess.Popen(  # noqa: S603 - fixed interpreter and test-controlled arguments
            [sys.executable, "-c", worker_code, str(SCRIPT), str(ledger), prefix]
        )
        for prefix in ("alpha", "bravo")
    ]
    for worker in workers:
        assert worker.wait(timeout=10) == 0
    rows = []
    for path in (ledger.with_suffix(".jsonl.1"), ledger):
        rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    assert {row["id"] for row in rows} == {
        f"{prefix}-{index}" for prefix in ("alpha", "bravo") for index in range(30)
    }
