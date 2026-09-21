"""Compile and validate bounded Pantheon assurance terminal payloads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from fdai_operator_service.families.conversation.contracts import JsonObject


def pantheon_assurance_payload(
    projection: Mapping[str, object],
) -> Mapping[str, object] | None:
    """Return the embedded Pantheon assurance record when one is present."""
    payload = projection.get("payload")
    value = payload.get("pantheon_assurance") if isinstance(payload, Mapping) else None
    return value if isinstance(value, Mapping) else None


def pantheon_done_event_data(assurance: Mapping[str, object]) -> JsonObject:
    """Compile one fail-closed no-authority Pantheon terminal event."""
    answer = assurance.get("answer")
    answer_generation = assurance.get("answer_generation")
    evaluator_models = assurance.get("pantheon_evaluator_models")
    trace = assurance.get("pantheon_trace")
    observations = assurance.get("pantheon_observations")
    reviews = assurance.get("pantheon_semantic_reviews")
    diagnostic = assurance.get("pantheon_diagnostic")
    prompt_profiles = assurance.get("pantheon_prompt_profiles")
    turn_timing = assurance.get("turn_timing")
    assessment_state = assurance.get("assessment_state", "unavailable")
    assessment_reasons = assurance.get("assessment_reasons", [])
    latency_ms = trace.get("latency_ms") if isinstance(trace, Mapping) else None
    if (
        assurance.get("schema_version") != "1.0.0"
        or not isinstance(answer, str)
        or not answer
        or not valid_answer_generation(answer_generation)
        or not valid_evaluator_models(evaluator_models)
        or not isinstance(trace, Mapping)
        or not isinstance(observations, Mapping)
        or not isinstance(reviews, list)
        or not isinstance(diagnostic, Mapping)
        or not valid_pantheon_prompt_profiles(prompt_profiles)
        or (turn_timing is not None and not isinstance(turn_timing, Mapping))
        or (
            latency_ms is not None
            and (not isinstance(latency_ms, int) or isinstance(latency_ms, bool) or latency_ms < 0)
        )
        or assessment_state not in {"completed", "deferred", "held", "unavailable"}
        or not isinstance(assessment_reasons, list)
        or any(not isinstance(reason, str) or not reason for reason in assessment_reasons)
        or assurance.get("execution_authority") is not False
    ):
        raise ValueError("stored Pantheon conversation assurance result is malformed")
    return cast(
        JsonObject,
        {
            "seq": 1,
            "revision": 0,
            "status": "answered" if assessment_state == "completed" else "held",
            "answer": answer,
            "answer_generation": (
                dict(cast(Mapping[str, object], answer_generation))
                if isinstance(answer_generation, Mapping)
                else {
                    "mode": "legacy_unattributed",
                    "model_identity": None,
                    "model_family": None,
                }
            ),
            "pantheon_evaluator_models": evaluator_models or [],
            "source": "pantheon-conversation-assurance",
            "assessment_id": assurance.get("assessment_id"),
            "assessment_state": assessment_state,
            "assessment_reasons": assessment_reasons,
            "trace_receipt_id": assurance.get("trace_receipt_id"),
            **({"latency_ms": latency_ms} if isinstance(latency_ms, int) else {}),
            **({"turn_timing": dict(turn_timing)} if isinstance(turn_timing, Mapping) else {}),
            "pantheon_trace": dict(trace),
            "pantheon_observations": dict(observations),
            "pantheon_semantic_reviews": reviews,
            "pantheon_diagnostic": dict(diagnostic),
            "pantheon_prompt_profiles": dict(cast(Mapping[str, object], prompt_profiles)),
            "execution_authority": False,
        },
    )


def valid_pantheon_prompt_profiles(value: object) -> bool:
    """Validate bounded content-free participant and evaluator prompt profiles."""
    if not isinstance(value, Mapping) or set(value) != {
        "answer_participants",
        "evaluator_profiles",
    }:
        return False
    participants = value.get("answer_participants")
    evaluators = value.get("evaluator_profiles")
    if (
        not isinstance(participants, list)
        or len(participants) > 3
        or not isinstance(evaluators, list)
        or len(evaluators) > 3
    ):
        return False
    participant_fields = {"agent", "prompt_version", "system_text_sha256", "situation"}
    evaluator_fields = {
        "profile_id",
        "profile_version",
        "profile_digest",
        "system_text_sha256",
        "system_token_budget",
        "request_token_budget",
        "reserved_output_tokens",
    }
    return all(
        isinstance(item, Mapping)
        and set(item) == participant_fields
        and all(isinstance(item.get(key), str) and item[key] for key in participant_fields)
        for item in participants
    ) and all(
        isinstance(item, Mapping)
        and set(item) == evaluator_fields
        and isinstance(item.get("profile_id"), str)
        and isinstance(item.get("profile_version"), int)
        and not isinstance(item.get("profile_version"), bool)
        and isinstance(item.get("profile_digest"), str)
        and isinstance(item.get("system_text_sha256"), str)
        and all(
            isinstance(item.get(key), int)
            and not isinstance(item.get(key), bool)
            and item[key] >= 0
            for key in (
                "system_token_budget",
                "request_token_budget",
                "reserved_output_tokens",
            )
        )
        for item in evaluators
    )


def valid_answer_generation(value: object) -> bool:
    """Validate content-free answer generation attribution."""
    if value is None:
        return True
    if not isinstance(value, Mapping) or set(value) != {
        "mode",
        "model_identity",
        "model_family",
    }:
        return False
    mode = value.get("mode")
    identity = value.get("model_identity")
    family = value.get("model_family")
    return mode in {"agent_projection", "semantic_model", "t2_model"} and (
        (identity is None and family is None and mode == "agent_projection")
        or (
            isinstance(identity, str)
            and bool(identity.strip())
            and family is None
            and mode == "semantic_model"
        )
        or (
            isinstance(identity, str)
            and bool(identity.strip())
            and isinstance(family, str)
            and bool(family.strip())
            and mode == "t2_model"
        )
    )


def valid_evaluator_models(value: object) -> bool:
    """Validate the bounded distinct-model evaluator projection shape."""
    return (
        value is None
        or isinstance(value, list)
        and len(value) <= 3
        and all(
            isinstance(item, Mapping)
            and set(item) == {"model_identity", "model_family", "output_available"}
            and isinstance(item.get("model_identity"), str)
            and bool(str(item["model_identity"]).strip())
            and isinstance(item.get("model_family"), str)
            and bool(str(item["model_family"]).strip())
            and type(item.get("output_available")) is bool
            for item in value
        )
    )
