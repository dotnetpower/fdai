from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "deployment"
    / "azure"
    / "verify_active_model_attestation.py"
)


@pytest.fixture(scope="module")
def module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_active_model_attestation", _SCRIPT)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def _record(digest: str) -> dict[str, object]:
    return {
        "verificationResult": {
            "statement": {"predicate": {"resolved_models": {"canonical_json_sha256": digest}}}
        }
    }


def _write(root: Path, payload: object) -> Path:
    path = root / "attestations.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_returns_one_verified_digest(module: ModuleType, tmp_path: Path) -> None:
    digest = "a" * 64
    path = _write(tmp_path, [_record(digest), _record(digest)])

    assert module.active_model_digest(path) == digest


def test_cli_failure_remains_visible_through_stdout_capture(
    module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _write(tmp_path, [])
    monkeypatch.setattr(sys, "argv", [str(_SCRIPT), "--attestations", str(path)])

    assert module.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "active model attestation verification failed: "
        "active model attestations MUST be a non-empty array\n"
    )


@pytest.mark.parametrize(
    "payload",
    [
        [],
        [_record("bad")],
        [_record("a" * 64), _record("b" * 64)],
        [{"verificationResult": {"statement": {"predicate": {}}}}],
    ],
)
def test_rejects_incomplete_or_conflicting_attestations(
    module: ModuleType,
    tmp_path: Path,
    payload: object,
) -> None:
    with pytest.raises(module.ActiveModelAttestationError):
        module.active_model_digest(_write(tmp_path, payload))
