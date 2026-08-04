"""Kubernetes scheduler event classifier tests."""

from __future__ import annotations

import pytest

from fdai.delivery.kubernetes.scheduler_events import classify_scheduler_failure


@pytest.mark.parametrize(
    "message",
    [
        "3 node(s) didn't have free ports for the requested pod ports",
        "1 node did not have free ports for requested pod ports",
    ],
)
def test_scheduler_classifier_recognizes_reviewed_host_port_phrases(message: str) -> None:
    failure = classify_scheduler_failure(reason="FailedScheduling", message=message)

    assert failure is not None
    assert failure.code == "host_port_conflict"


@pytest.mark.parametrize(
    ("reason", "message"),
    [
        ("Scheduled", "node didn't have free ports for the requested pod ports"),
        ("FailedScheduling", "0/3 nodes are available"),
        ("FailedCreate", "didn't have free ports for the requested pod ports"),
    ],
)
def test_scheduler_classifier_rejects_unreviewed_context(reason: str, message: str) -> None:
    assert classify_scheduler_failure(reason=reason, message=message) is None
