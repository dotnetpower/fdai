#!/usr/bin/env python3
"""Hydrate service tfvars with authoritative platform Event Bus topics."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from typing import Any

from service_contract import ServiceContractError, resolve_service

_TOPIC_PATTERN = re.compile(r"fdai\.[a-z0-9-]+\.events")


class EventTopicError(ValueError):
    """Raised when the authoritative topic or selected tfvars object is invalid."""


def normalize_event_topic(value: str) -> str:
    """Return one canonical FDAI event topic or fail closed."""
    topic = value.strip()
    if _TOPIC_PATTERN.fullmatch(topic) is None:
        raise EventTopicError("event topic must use the canonical fdai.<domain>.events form")
    return topic


def _fixed_topic(value: str, *, expected: str, label: str) -> str:
    topic = value.strip()
    if topic != expected:
        raise EventTopicError(f"{label} must be {expected}")
    return topic


def hydrate_event_topic(
    payload: dict[str, Any],
    *,
    service: str,
    environment: str,
    event_topic: str,
    pipeline_stage_topic: str,
    pantheon_object_topic: str,
) -> dict[str, Any]:
    """Copy tfvars and replace only the selected service's platform-owned topics."""
    resolve_service(service, environment)
    environments = payload.get("environments")
    if not isinstance(environments, dict):
        raise EventTopicError("tfvars payload must contain an environments object")
    services = environments.get(environment)
    if not isinstance(services, dict):
        raise EventTopicError(f"tfvars payload has no {environment} environment object")
    selected = services.get(service)
    if not isinstance(selected, dict) or not selected:
        raise EventTopicError(f"tfvars payload has no non-empty entry for {service}")

    topics_by_service = {
        "core-control-plane": {"events": normalize_event_topic(event_topic)},
        "operator-service": {
            "events": normalize_event_topic(event_topic),
            "semantic_requests": "operator.semantic-turn.requests",
            "semantic_projections": "core.semantic-turn.projections",
            "semantic_physical": _fixed_topic(
                pantheon_object_topic,
                expected="fdai.pantheon.objects",
                label="Pantheon object topic",
            ),
            "read_investigation_requests": "operator.read-investigation.requests",
            "incident_intervention_requests": "operator.incident-intervention.requests",
            "read_investigation_completions": "core.read-investigation.completions",
            "hil_decisions": "fdai.hil.decisions",
            "notification_receipts": "fdai.notifications.delivery-receipts",
        },
        "document-ingestion-api": {
            "pipeline_stages": _fixed_topic(
                pipeline_stage_topic,
                expected="fdai.pipeline.stages",
                label="pipeline stage topic",
            )
        },
        "document-processing-worker": {
            "pipeline_stages": _fixed_topic(
                pipeline_stage_topic,
                expected="fdai.pipeline.stages",
                label="pipeline stage topic",
            ),
            "pantheon_objects": _fixed_topic(
                pantheon_object_topic,
                expected="fdai.pantheon.objects",
                label="Pantheon object topic",
            ),
        },
    }
    hydrated = copy.deepcopy(payload)
    replacements = topics_by_service.get(service)
    if replacements is None:
        return hydrated
    event_topics = selected.get("event_topics")
    if not isinstance(event_topics, dict):
        raise EventTopicError("selected service tfvars must contain an event_topics object")
    hydrated["environments"][environment][service]["event_topics"].update(replacements)
    return hydrated


def main() -> int:
    """Read tfvars from stdin and emit the event-topic-hydrated payload to stdout."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--event-topic", required=True)
    parser.add_argument("--pipeline-stage-topic", required=True)
    parser.add_argument("--pantheon-object-topic", required=True)
    args = parser.parse_args()
    try:
        raw = json.load(sys.stdin)
        if not isinstance(raw, dict):
            raise EventTopicError("tfvars payload must be a JSON object")
        hydrated = hydrate_event_topic(
            raw,
            service=args.service,
            environment=args.environment,
            event_topic=args.event_topic,
            pipeline_stage_topic=args.pipeline_stage_topic,
            pantheon_object_topic=args.pantheon_object_topic,
        )
        json.dump(hydrated, sys.stdout, separators=(",", ":"), sort_keys=True)
        sys.stdout.write("\n")
    except (json.JSONDecodeError, ServiceContractError, EventTopicError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
