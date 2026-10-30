from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta

import pytest

from fdai_deployment_cli import bootstrap_channel as channel

SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"


def install_payload(**changes):
    return {
        "subscription_id": SUBSCRIPTION,
        "region": "eastus",
        "monthly_cost_ceiling": 500,
        "artifact_source": "source",
        "source_root": "/example/checkout",
        **changes,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"subscription_id": "not-a-uuid"},
        {"region": "../eastus"},
        {"monthly_cost_ceiling": True},
        {"monthly_cost_ceiling": 0},
        {"artifact_source": "fallback"},
        {"artifact_source": []},
        {"source_root": None},
        {"unexpected": True},
        {"hub_public_key": "PRIVATE KEY"},
        {"source_root": "x\0y"},
    ],
)
def test_install_boundary_rejects_malformed_inputs(tmp_path, changes):
    with pytest.raises(ValueError):
        channel.submit_request(tmp_path, "install", install_payload(**changes))
    assert not (tmp_path / "channel.json").exists()


def test_private_atomic_single_request_and_safe_projection(tmp_path):
    root = tmp_path / "setup"
    status = channel.submit_request(root, "install", install_payload())
    assert status["phase"] == "working"
    assert set(status) == set(channel.initial_status())
    assert "payload" not in channel.read_status(root)
    with pytest.raises(ValueError, match="already"):
        channel.submit_request(root, "accounts", {})
    assert root.stat().st_mode & 0o777 == 0o700
    for path in root.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "action,payload",
    [
        ("unknown", {}),
        ("resume", {"region": "eastus"}),
        ("inspect", {"source_root": "replacement"}),
    ],
)
def test_noninstall_actions_never_replace_configuration(tmp_path, action, payload):
    with pytest.raises(ValueError):
        channel.submit_request(tmp_path, action, payload)


def review_record(root, *, expired=False):
    status = channel.submit_request(root, "inspect", {})
    review = {
        "id": "review-1",
        "digest": "a" * 64,
        "title": "Exact review",
        "details": [],
        "confirmation_required": "application-apply-destructive",
        "expires_at": (datetime.now(UTC) + timedelta(seconds=-1 if expired else 600)).isoformat(),
    }
    record = channel._read(root)
    record["pending"] = None
    record["status"].update(phase="review", review=review)
    channel._write(root, record)
    return {
        "request_id": status["request_id"],
        "review_id": review["id"],
        "digest": review["digest"],
        "approved": True,
        "confirmation": review["confirmation_required"],
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"request_id": "other"},
        {"review_id": "other"},
        {"digest": "b" * 64},
        {"confirmation": "yes"},
        {"approved": "true"},
        {"extra": "no"},
    ],
)
def test_decisions_bind_exact_current_request_review_and_confirmation(tmp_path, changes):
    payload = review_record(tmp_path)
    with pytest.raises(ValueError):
        channel.submit_decision(tmp_path, {**payload, **changes})
    assert channel.read_status(tmp_path)["phase"] == "review"


def test_decision_is_one_shot_and_expired_review_is_rejected(tmp_path):
    payload = review_record(tmp_path)
    assert channel.submit_decision(tmp_path, payload)["phase"] == "working"
    with pytest.raises(ValueError):
        channel.submit_decision(tmp_path, payload)
    other = tmp_path / "expired"
    with pytest.raises(ValueError, match="expired"):
        channel.submit_decision(other, review_record(other, expired=True))


def test_stale_review_is_interrupted_never_ready(tmp_path):
    review_record(tmp_path)
    record = channel._read(tmp_path)
    record["heartbeat"] = time.time() - 60
    record["status"]["deployment_ready"] = True
    channel._write(tmp_path, record)
    status = channel.read_status(tmp_path)
    assert status["phase"] == "interrupted"
    assert status["review"] is None
    assert status["deployment_ready"] is False


def test_final_status_is_not_visible_until_owned_operation_is_reaped(tmp_path):
    channel.prepare_directory(tmp_path)
    record = {
        "status": {**channel.initial_status(), "phase": "ready", "deployment_ready": True},
        "active_request_id": "still-owned",
        "heartbeat": time.time(),
    }
    channel._write(tmp_path, record)
    assert channel.read_status(tmp_path)["phase"] == "working"
    assert channel.read_status(tmp_path)["deployment_ready"] is False
    with pytest.raises(ValueError, match="already"):
        channel.submit_request(tmp_path, "accounts", {})
    record["active_request_id"] = None
    channel._write(tmp_path, record)
    assert channel.read_status(tmp_path)["phase"] == "ready"


@pytest.mark.parametrize("raw", [b'{"status":{},"status":{}}', b'{"heartbeat":NaN}'])
def test_private_state_rejects_duplicate_fields_and_nonfinite_values(tmp_path, raw):
    path = tmp_path / "channel.json"
    path.write_bytes(raw)
    path.chmod(0o600)
    with pytest.raises(ValueError, match="malformed"):
        channel.read_status(tmp_path)


def test_symlinks_hardlinks_and_unsafe_permissions_are_rejected(tmp_path):
    root = tmp_path / "private"
    channel.prepare_directory(root)
    outside = tmp_path / "outside"
    outside.write_text("{}")
    (root / "channel.json").symlink_to(outside)
    with pytest.raises(ValueError):
        channel.read_status(root)
    (root / "channel.json").unlink()
    outside.chmod(0o600)
    os.link(outside, root / "channel.json")
    with pytest.raises(ValueError):
        channel.read_status(root)
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError):
        channel.prepare_directory(alias)
    root.chmod(0o755)
    with pytest.raises(ValueError):
        channel.prepare_directory(root)
