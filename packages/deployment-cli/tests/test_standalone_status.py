from __future__ import annotations

import json

import pytest

from fdai_deployment_cli.standalone_status import current_status, prior_attempt


def _status(**overrides):
    return {
        "schema_version": "fdai.genesis-orchestration-status.v2",
        "attempt": 2,
        "sequence": 12,
        "mode": "apply",
        "state": "waiting",
        "route": "private-runner",
        "current_stage": "application-plan",
        "completed_stages": ["foundation-state"],
        "source_commit": "a" * 40,
        "target_binding": "b" * 64,
        **overrides,
    }


def _write(path, value):
    path.parent.mkdir(exist_ok=True, mode=0o700)
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)


def test_fresh_target_bound_status_is_accepted(tmp_path) -> None:
    path = tmp_path / "run/status.json"
    assert prior_attempt(path) == 0
    _write(path, _status(attempt=1))
    previous = prior_attempt(path)
    assert previous == 1
    _write(path, _status())
    current = current_status(path, previous=previous, source_commit="a" * 40, run_binding="b" * 64)
    assert current["attempt"] == 2


@pytest.mark.parametrize(
    "overrides",
    [
        {"attempt": 1},
        {"attempt": 3},
        {"attempt": 0},
        {"attempt": True},
        {"attempt": "2"},
        {"sequence": 0},
        {"sequence": True},
        {"state": "failed"},
        {"state": "running"},
        {"state": []},
        {"target_binding": "c" * 64},
        {"source_commit": "c" * 40},
        {"mode": "inspect"},
        {"schema_version": "future"},
    ],
)
def test_stale_or_mismatched_status_is_not_current(tmp_path, overrides) -> None:
    path = tmp_path / "run/status.json"
    _write(path, _status(**overrides))
    with pytest.raises(ValueError, match="current Foundation status"):
        current_status(path, previous=1, source_commit="a" * 40, run_binding="b" * 64)


def test_missing_current_status_has_safe_actionable_error(tmp_path) -> None:
    path = tmp_path / "run/status.json"
    with pytest.raises(ValueError, match="did not publish current Foundation status") as error:
        current_status(path, previous=0, source_commit="a" * 40, run_binding="b" * 64)
    assert str(path) not in str(error.value)


def test_status_symlink_is_never_followed(tmp_path) -> None:
    path = tmp_path / "run/status.json"
    _write(path, _status())
    linked = path.with_name("linked.json")
    linked.symlink_to(path)
    with pytest.raises(OSError):
        prior_attempt(linked)


def test_non_object_status_is_rejected(tmp_path) -> None:
    path = tmp_path / "run/status.json"
    _write(path, [])
    with pytest.raises(ValueError, match="must be an object"):
        current_status(path, previous=0, source_commit="a" * 40, run_binding="b" * 64)
