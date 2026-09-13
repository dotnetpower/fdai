"""Exercise value-safe diagnostics using only synthetic private records."""

from __future__ import annotations

import json

import pytest

from fdai_deployment_cli.foundation_failure import foundation_failure_summary

GENERIC = "standalone Foundation orchestration failed; inspect retained status before recovery"


@pytest.fixture
def status(tmp_path):
    tmp_path.chmod(0o700)
    value = {
        "schema_version": "fdai.genesis-orchestration-status.v2",
        "attempt": 2,
        "sequence": 5,
        "source_commit": "a" * 40,
        "target_binding": "b" * 64,
        "mode": "apply",
        "state": "blocked",
        "route": "private-runner",
        "current_stage": "runner-image-apply",
        "reason_code": "runner_image_apply_or_verification_failed",
    }
    path = tmp_path / "status.json"

    def write(payload):
        path.write_text(json.dumps(payload))
        path.chmod(0o600)
        return path

    return value, write


def summarize(path):
    return foundation_failure_summary(
        path, previous=1, source_commit="a" * 40, run_binding="b" * 64
    )


@pytest.mark.parametrize("state", ["blocked", "failed"])
def test_image_failure_explains_verification_only_recovery_without_leaking_values(status, state):
    value, write = status
    value.update(state=state, next_action="private-marker", raw_error="private-provider-output")
    path = write(value)
    before = path.read_bytes(), path.stat().st_mtime_ns
    message = summarize(path)
    assert "Runner image exact apply (08/15)" in message
    assert "creation or independent verification is incomplete" in message
    assert "verification only" in message
    assert "new approval" in message
    assert "Preserve the work directory" in message
    assert "private-marker" not in message
    assert "private-provider-output" not in message
    assert str(path) not in message
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("schema_version", "future-schema"),
        ("attempt", 1),
        ("attempt", 3),
        ("attempt", True),
        ("attempt", "2"),
        ("sequence", 0),
        ("sequence", True),
        ("sequence", "5"),
        ("source_commit", "c" * 40),
        ("target_binding", "c" * 64),
        ("mode", "inspect"),
        ("state", "waiting"),
        ("state", "complete"),
        ("state", []),
        ("route", "public-dev"),
        ("current_stage", "foundation-apply"),
        ("current_stage", "\x1b[2Jprivate-marker"),
        ("reason_code", "unknown-private-marker"),
    ],
)
def test_untrusted_or_nonfailed_context_keeps_original_error(status, field, replacement):
    value, write = status
    value[field] = replacement
    assert summarize(write(value)) == GENERIC


@pytest.mark.parametrize("payload", [[], None, "private-marker", 2, {}])
def test_non_object_or_incomplete_record_cannot_explain_failure(status, payload):
    _value, write = status
    assert summarize(write(payload)) == GENERIC


@pytest.mark.parametrize("fault", ["missing", "mode", "symlink", "invalid", "oversized", "utf8"])
def test_private_read_failures_do_not_replace_the_original_error(status, fault):
    value, write = status
    path = write(value)
    if fault == "missing":
        path.unlink()
    elif fault == "mode":
        path.chmod(0o644)
    elif fault == "symlink":
        link = path.with_name("linked.json")
        link.symlink_to(path)
        path = link
    elif fault == "invalid":
        path.write_text("{private-marker")
    elif fault == "oversized":
        path.write_text("x" * 1_048_577)
    else:
        path.write_bytes(b"\xff")
    assert summarize(path) == GENERIC


@pytest.mark.parametrize("suffix", ['"attempt": 2', '"extra": NaN', '"extra": Infinity'])
def test_duplicate_keys_and_nonfinite_values_are_rejected(status, suffix):
    value, write = status
    path = write(value)
    path.write_text(json.dumps(value)[:-1] + "," + suffix + "}")
    assert summarize(path) == GENERIC


def test_deeply_nested_json_does_not_mask_original_error(status):
    value, write = status
    path = write(value)
    path.write_text("[" * 2000 + "0" + "]" * 2000)
    assert summarize(path) == GENERIC
