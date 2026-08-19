"""Pure Teams, Slack, and custom presentation renderer contract tests."""

from __future__ import annotations

import json
from dataclasses import replace

import fdai.shared.providers as providers
import pytest
from fdai.delivery.channels import (
    SLACK_PRESENTATION_CAPABILITIES,
    TEAMS_PRESENTATION_CAPABILITIES,
    SlackPresentationRenderer,
    TeamsPresentationRenderer,
    normalize_channel_presentation,
)
from fdai.delivery.channels.common import build_fallback_text, payload_size
from fdai.shared.providers.channel_presentation import (
    ChannelPresentationCapabilities,
    ChannelPresentationEnvelope,
    ChannelPresentationPayload,
    ChannelPresentationRenderer,
    ChannelPresentationRenderError,
)
from fdai.shared.providers.conversation_channel import (
    ConversationChannelKind,
    OutboundResponse,
    outbound_response_from_json,
    outbound_response_to_json,
)

_REF = "ontology-function:verified-output"


def _artifact() -> dict[str, object]:
    return {
        "schema_version": 2,
        "layout": "stack",
        "evidence_refs": [_REF],
        "blocks": [
            {
                "slot_id": "trend",
                "kind": "time_series",
                "title": "Request trend",
                "emphasis": "primary",
                "collapsed": False,
                "evidence_refs": [_REF],
                "data": {
                    "description": "Ordered observations for requests.",
                    "metric": "requests",
                    "unit": "count",
                    "points": [
                        {"timestamp": "2026-08-19T00:00:00Z", "value": 1},
                        {"timestamp": "2026-08-19T00:01:00Z", "value": 3},
                        {"timestamp": "2026-08-19T00:02:00Z", "value": 2},
                    ],
                    "exact_table": {
                        "columns": [
                            {"key": "c0", "label": "timestamp"},
                            {"key": "c1", "label": "value"},
                        ],
                        "rows": [
                            {"c0": "2026-08-19T00:00:00Z", "c1": "1"},
                            {"c0": "2026-08-19T00:01:00Z", "c1": "3"},
                            {"c0": "2026-08-19T00:02:00Z", "c1": "2"},
                        ],
                        "status_key": None,
                    },
                },
            },
            {
                "slot_id": "limitations",
                "kind": "callout",
                "title": "Limitations",
                "emphasis": "supporting",
                "collapsed": False,
                "evidence_refs": [_REF],
                "data": {
                    "tone": "warning",
                    "lines": ["One source is unavailable."],
                },
            },
        ],
    }


def _response(*, artifact: object | None = None) -> OutboundResponse:
    data: dict[str, object] = {
        "execution_authority": False,
        "authority": "server_read_model",
        "limitations": ["The result is partial."],
    }
    if artifact is not None:
        data["presentation_artifact"] = artifact
    return OutboundResponse(
        channel_kind=ConversationChannelKind.SLACK,
        channel_id="channel-example",
        in_reply_to="message-example",
        thread_id="thread-example",
        status="verified",
        text=(
            "Requests were 1, 3, and 2 at the three verified timestamps. One source is unavailable."
        ),
        data=data,
        evidence_refs=(_REF,),
    )


def test_teams_slack_and_custom_preserve_canonical_mandatory_facts() -> None:
    envelope = normalize_channel_presentation(_response(artifact=_artifact()), web_url="/deck")

    teams = TeamsPresentationRenderer().render(envelope)
    slack = SlackPresentationRenderer().render(envelope)
    custom = _FakeCustomRenderer().render(envelope)

    assert isinstance(_FakeCustomRenderer(), ChannelPresentationRenderer)
    assert envelope.artifact_version == 2
    assert envelope.sections[0].kind == "time_series"
    assert [fact.value for fact in envelope.sections[0].facts] == ["1", "3", "2"]
    assert teams.fallback_text == slack.fallback_text == custom.fallback_text
    for required in (
        envelope.canonical_text,
        "The result is partial.",
        "One source is unavailable.",
        _REF,
        "Authority: server_read_model",
        "Execution authority: none",
    ):
        assert required in teams.fallback_text
    assert "schema_version" not in json.dumps(teams.body)
    assert "schema_version" not in json.dumps(slack.body)
    assert payload_size(teams.body) <= TEAMS_PRESENTATION_CAPABILITIES.max_serialized_bytes
    assert payload_size(slack.body) <= SLACK_PRESENTATION_CAPABILITIES.max_serialized_bytes


def test_malformed_artifact_fails_closed_to_canonical_text() -> None:
    malformed = _artifact()
    malformed["blocks"][0]["kind"] = "html"  # type: ignore[index]

    envelope = normalize_channel_presentation(_response(artifact=malformed))
    payload = SlackPresentationRenderer().render(envelope)

    assert envelope.artifact_version is None
    assert envelope.sections == ()
    assert envelope.artifact_degraded is True
    assert payload.degraded_to_text is True
    assert envelope.canonical_text in payload.fallback_text
    assert "html" not in json.dumps(payload.body)


def test_custom_renderer_fails_when_mandatory_text_exceeds_its_profile() -> None:
    capabilities = replace(
        _CUSTOM_CAPABILITIES,
        max_text_chars=256,
    )
    renderer = _FakeCustomRenderer(capabilities)
    envelope = normalize_channel_presentation(
        replace(
            _response(artifact=_artifact()),
            evidence_refs=("evidence:" + ("x" * 400),),
            data={
                "execution_authority": False,
                "authority": "server_read_model",
                "limitations": ["Required limitation"],
            },
        )
    )

    with pytest.raises(ChannelPresentationRenderError, match="mandatory"):
        renderer.render(envelope)


def test_outbound_response_durable_replay_preserves_v2_artifact_exactly() -> None:
    response = _response(artifact=_artifact())

    restored = outbound_response_from_json(outbound_response_to_json(response))

    assert restored.data == response.data
    assert restored.data["presentation_artifact"] == _artifact()
    assert restored.evidence_refs == response.evidence_refs


def test_public_provider_facade_exports_only_renderer_definitions() -> None:
    assert providers.ChannelPresentationRenderer is ChannelPresentationRenderer
    assert not hasattr(providers, "TeamsPresentationRenderer")
    assert not hasattr(providers, "SlackPresentationRenderer")


_CUSTOM_CAPABILITIES = ChannelPresentationCapabilities(
    profile_id="custom-test-v1",
    max_text_chars=2_000,
    max_serialized_bytes=8_000,
    max_blocks=4,
    max_block_text_chars=2_000,
    max_fields=16,
    max_actions=0,
)


class _FakeCustomRenderer:
    renderer_id = "custom-test"

    def __init__(
        self,
        capabilities: ChannelPresentationCapabilities = _CUSTOM_CAPABILITIES,
    ) -> None:
        self.capabilities = capabilities

    def render(self, envelope: ChannelPresentationEnvelope) -> ChannelPresentationPayload:
        fallback, degraded = build_fallback_text(envelope, self.capabilities)
        return ChannelPresentationPayload(
            renderer_id=self.renderer_id,
            body={"text": fallback},
            fallback_text=fallback,
            degraded_to_text=degraded,
        )
