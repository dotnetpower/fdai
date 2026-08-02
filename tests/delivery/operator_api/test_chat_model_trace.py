from __future__ import annotations

from fdai.delivery.operator_api.routes.chat_model_trace import (
    activate_model_trace,
    begin_model_call,
    complete_model_call,
    deactivate_model_trace,
    snapshot_model_trace,
)


def test_disabled_scope_collects_nothing() -> None:
    scope = activate_model_trace(False)
    try:
        call = begin_model_call(
            kind="answer",
            model="test-model",
            messages=({"role": "user", "content": "hello"},),
        )
        assert call is None
        assert snapshot_model_trace(scope.collector) is None
    finally:
        deactivate_model_trace(scope)


def test_trace_preserves_roles_and_hashes_while_redacting_sensitive_values() -> None:
    synthetic_guid = "11111111" + "-2222-3333-4444-555555555555"
    scope = activate_model_trace(True)
    try:
        call = begin_model_call(
            kind="structured:turn-plan",
            model="test-model",
            messages=(
                {
                    "role": "system",
                    "content": (
                        "Authorization: Bearer example-token "
                        f"tenant={synthetic_guid} "
                        "endpoint=https://service.example.net/path\n"
                        "Current view snapshot (JSON):\n"
                        '{"resource":"prod-db-01"}'
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "contact user@example.com"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                    ],
                },
            ),
        )
        complete_model_call(
            call,
            response_content='{"answer":"ok","api_key":"example-secret"}',
            usage={"prompt_tokens": 10, "completion_tokens": 4, "ignored": 99},
        )
        payload = snapshot_model_trace(scope.collector)
    finally:
        deactivate_model_trace(scope)

    assert payload is not None
    assert payload["schema_version"] == 1
    assert payload["redacted"] is True
    trace = payload["calls"][0]
    assert [item["role"] for item in trace["request"]["messages"]] == ["system", "user"]
    serialized = str(payload)
    assert "example-token" not in serialized
    assert synthetic_guid not in serialized
    assert "service.example.net" not in serialized
    assert "user@example.com" not in serialized
    assert "example-secret" not in serialized
    assert "AAAA" not in serialized
    assert "prod-db-01" not in serialized
    assert len(trace["request"]["sha256"]) == 64
    assert len(trace["response"]["sha256"]) == 64
    assert trace["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 4,
    }
    rules = {item["rule"] for item in trace["redactions"]}
    assert {
        "bearer-token",
        "current-view-snapshot",
        "email",
        "guid",
        "named-secret",
        "non-text-content",
        "url",
    } <= rules


def test_trace_bounds_calls_and_marks_unfinished_calls() -> None:
    scope = activate_model_trace(True)
    try:
        for index in range(10):
            begin_model_call(
                kind=f"call-{index}",
                model="test-model",
                messages=({"role": "user", "content": "hello"},),
            )
        payload = snapshot_model_trace(scope.collector)
    finally:
        deactivate_model_trace(scope)

    assert payload is not None
    assert len(payload["calls"]) == 8
    assert payload["omitted_calls"] == 2
    assert all(call["status"] == "incomplete" for call in payload["calls"])


def test_trace_marks_bounded_request_and_response_content() -> None:
    scope = activate_model_trace(True)
    try:
        call = begin_model_call(
            kind="answer",
            model="test-model",
            messages=({"role": "system", "content": "x" * 20_000},),
        )
        complete_model_call(call, response_content="y" * 10_000)
        payload = snapshot_model_trace(scope.collector)
    finally:
        deactivate_model_trace(scope)

    assert payload is not None
    traced = payload["calls"][0]
    assert traced["request"]["messages"][0]["content"].endswith("[TRUNCATED]")
    assert traced["response"]["content"].endswith("[TRUNCATED]")
    assert any(
        item == {"rule": "character-limit", "replacements": 2} for item in traced["redactions"]
    )
