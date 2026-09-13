"""Private Genesis Foundation planning adapter regressions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_DIR = _ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(_SCRIPT_DIR))

from genesis_foundation import (  # noqa: E402
    FoundationPlanError,
    FoundationPlanInputs,
    missing_foundation_report,
    prepare_foundation_plan,
)
from genesis_status import StatusStore  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_host_provider_preflight(monkeypatch):
    """This suite owns saved-plan orchestration; VM provider boundaries have dedicated tests."""
    monkeypatch.setattr("genesis_foundation.recheck_foundation_vm", lambda **_kwargs: None)


def _inputs(tmp_path: Path) -> FoundationPlanInputs:
    return FoundationPlanInputs(
        offline_kit=tmp_path / "offline-kit",
        release_root=tmp_path / "release-root.pem",
        bundle_public_key=tmp_path / "bundle-public-key.pem",
        profile=tmp_path / "profile.json",
        variables_file=tmp_path / "variables.json",
    )


def _saved_result(*, expires_at: str = "2999-09-10T12:00:00+00:00") -> str:
    return json.dumps(
        {
            "schema_version": "fdai.provision-plan.v1",
            "stage": "foundation",
            "state": "review",
            "apply_authorized": False,
            "mutation_performed": False,
            "subscription_ready": False,
            "saved_plan": {
                "schema_version": "fdai.foundation-saved-plan.v1",
                "state": "review",
                "apply_authorized": False,
                "mutation_performed": False,
                "subscription_ready": False,
                "review_digest": "a" * 64,
                "plan_digest": "b" * 64,
                "expires_at": expires_at,
            },
        }
    )


def test_missing_report_names_every_external_boundary_without_paths() -> None:
    report = missing_foundation_report()

    assert report["state"] == "waiting"
    assert report["required_count"] == 5
    assert report["supplied_count"] == 0
    assert report["missing"] == [
        "signed_offline_kit",
        "release_public_key",
        "bundle_public_key",
        "foundation_profile",
        "foundation_variables",
    ]
    assert report["apply_authorized"] is False
    assert report["subscription_ready"] is False
    assert not any("/" in str(value) for value in report.values())


def test_complete_inputs_generate_only_an_exact_saved_plan(tmp_path: Path) -> None:
    calls: list[tuple[tuple[str, ...], str, dict[str, object]]] = []

    def capture(command: tuple[str, ...], reason: str, **kwargs: object) -> str:
        calls.append((command, reason, kwargs))
        return _saved_result()

    report = prepare_foundation_plan(
        inputs=_inputs(tmp_path),
        repository_root=_ROOT,
        orchestration_work_dir=tmp_path / "run",
        attempt=3,
        prior_report=None,
        timeout=900,
        capture=capture,
    )

    assert len(calls) == 1
    command, reason, options = calls[0]
    assert command[:6] == (
        "uv",
        "run",
        "--frozen",
        "--project",
        str(_ROOT / "packages/deployment-cli"),
        "fdaictl",
    )
    assert command[6:10] == ("provision", "plan", "--stage", "foundation")
    assert "--save-plan" in command
    assert "apply" not in command
    assert command[command.index("--work-dir") + 1].endswith("/foundation-plan-attempt-3")
    assert reason == "foundation_plan_generation_failed"
    assert options == {"strip": False, "timeout": 900}
    assert report == {
        "schema_version": "fdai.genesis-foundation-plan.v1",
        "state": "review",
        "plan_ref": "foundation-plan-attempt-3",
        "attempt": 3,
        "review_digest": "a" * 64,
        "plan_digest": "b" * 64,
        "expires_at": "2999-09-10T12:00:00+00:00",
        "integrity_verified": True,
        "apply_authorized": False,
        "mutation_performed": False,
        "subscription_ready": False,
    }


def test_unexpired_prior_plan_is_reverified_without_replanning(tmp_path: Path) -> None:
    prior = json.loads(
        json.dumps(
            {
                "schema_version": "fdai.genesis-foundation-plan.v1",
                "state": "review",
                "plan_ref": "foundation-plan-attempt-1",
                "attempt": 1,
                "review_digest": "a" * 64,
                "plan_digest": "b" * 64,
                "expires_at": "2999-09-10T12:00:00+00:00",
                "integrity_verified": True,
                "apply_authorized": False,
                "mutation_performed": False,
                "subscription_ready": False,
            }
        )
    )
    calls: list[tuple[str, ...]] = []

    def capture(command: tuple[str, ...], _reason: str, **_kwargs: object) -> str:
        calls.append(command)
        return json.dumps(
            {
                "schema_version": "fdai.foundation-plan-integrity.v1",
                "state": "review",
                "review_digest": "a" * 64,
                "plan_digest": "b" * 64,
                "integrity_verified": True,
                "apply_authorized": False,
                "mutation_performed": False,
                "subscription_ready": False,
            }
        )

    report = prepare_foundation_plan(
        inputs=_inputs(tmp_path),
        repository_root=_ROOT,
        orchestration_work_dir=tmp_path / "run",
        attempt=2,
        prior_report=prior,
        timeout=900,
        capture=capture,
    )

    assert report == prior
    assert len(calls) == 1
    assert calls[0][6:8] == ("provision", "verify-foundation-plan")
    assert "plan" not in calls[0][6:]


def test_expired_prior_plan_creates_a_new_attempt(tmp_path: Path) -> None:
    prior = {
        "schema_version": "fdai.genesis-foundation-plan.v1",
        "state": "review",
        "plan_ref": "foundation-plan-attempt-1",
        "attempt": 1,
        "review_digest": "a" * 64,
        "plan_digest": "b" * 64,
        "expires_at": "2000-09-10T12:00:00+00:00",
        "integrity_verified": True,
        "apply_authorized": False,
        "mutation_performed": False,
        "subscription_ready": False,
    }
    calls: list[tuple[str, ...]] = []

    def capture(command: tuple[str, ...], _reason: str, **_kwargs: object) -> str:
        calls.append(command)
        return _saved_result()

    report = prepare_foundation_plan(
        inputs=_inputs(tmp_path),
        repository_root=_ROOT,
        orchestration_work_dir=tmp_path / "run",
        attempt=2,
        prior_report=prior,
        timeout=900,
        capture=capture,
    )

    assert calls[0][6:8] == ("provision", "plan")
    assert report["plan_ref"] == "foundation-plan-attempt-2"


def test_status_preserves_exact_plan_report_for_retry(tmp_path: Path) -> None:
    work = tmp_path / "status"
    work.mkdir(mode=0o700)
    report = {
        "schema_version": "fdai.genesis-foundation-plan.v1",
        "state": "review",
        "plan_ref": "foundation-plan-attempt-1",
        "attempt": 1,
        "review_digest": "a" * 64,
        "plan_digest": "b" * 64,
        "expires_at": "2999-09-10T12:00:00+00:00",
        "integrity_verified": True,
        "apply_authorized": False,
        "mutation_performed": False,
        "subscription_ready": False,
    }
    first = StatusStore(
        path=work / "status.json",
        source_commit="c" * 40,
        target_binding="d" * 64,
        mode="apply",
        deadline_at="2999-09-10T12:00:00Z",
    )
    first.foundation_report = report
    first.update(stage="foundation-plan", state="waiting")

    retry = StatusStore(
        path=work / "status.json",
        source_commit="c" * 40,
        target_binding="d" * 64,
        mode="apply",
        deadline_at="2999-09-10T13:00:00Z",
    )

    assert retry.foundation_report == report
    assert retry.attempt == 2


@pytest.mark.parametrize(
    "mutation",
    ["apply", "mutation", "ready", "review-digest", "expires", "offset"],
)
def test_invalid_or_authority_bearing_plan_result_is_rejected(
    tmp_path: Path, mutation: str
) -> None:
    result = json.loads(_saved_result())
    saved = result["saved_plan"]
    assert isinstance(saved, dict)
    if mutation == "apply":
        result["apply_authorized"] = True
    elif mutation == "mutation":
        saved["mutation_performed"] = True
    elif mutation == "ready":
        saved["subscription_ready"] = True
    elif mutation == "review-digest":
        saved["review_digest"] = "invalid"
    elif mutation == "expires":
        saved["expires_at"] = "not-a-time"
    else:
        saved["expires_at"] = "2999-09-10T13:00:00+01:00"

    with pytest.raises(FoundationPlanError):
        prepare_foundation_plan(
            inputs=_inputs(tmp_path),
            repository_root=_ROOT,
            orchestration_work_dir=tmp_path / "run",
            attempt=1,
            prior_report=None,
            timeout=900,
            capture=lambda *_args, **_kwargs: json.dumps(result),
        )


def test_relative_inputs_are_rejected_before_external_execution(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    relative = FoundationPlanInputs(
        offline_kit=Path("offline-kit"),
        release_root=inputs.release_root,
        bundle_public_key=inputs.bundle_public_key,
        profile=inputs.profile,
        variables_file=inputs.variables_file,
    )

    with pytest.raises(FoundationPlanError, match="absolute"):
        prepare_foundation_plan(
            inputs=relative,
            repository_root=_ROOT,
            orchestration_work_dir=tmp_path / "run",
            attempt=1,
            prior_report=None,
            timeout=900,
            capture=lambda *_args, **_kwargs: pytest.fail("external command was invoked"),
        )
