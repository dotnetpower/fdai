#!/usr/bin/env python3
"""Hydrate service tfvars with the authoritative primary Event Bus topic."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from typing import Any

from service_contract import ServiceContractError, resolve_service

_EVENT_TOPIC_SERVICES = frozenset({"core-control-plane", "operator-service"})
_TOPIC_PATTERN = re.compile(r"fdai\.[a-z0-9-]+\.events")


class EventTopicError(ValueError):
    """Raised when the authoritative topic or selected tfvars object is invalid."""


def normalize_event_topic(value: str) -> str:
    """Return one canonical FDAI event topic or fail closed."""
    topic = value.strip()
    if _TOPIC_PATTERN.fullmatch(topic) is None:
        raise EventTopicError("event topic must use the canonical fdai.<domain>.events form")
    return topic


def hydrate_event_topic(
    payload: dict[str, Any],
    *,
    service: str,
    environment: str,
    event_topic: str,
) -> dict[str, Any]:
    """Copy tfvars and replace the selected service's platform-owned ingress topic."""
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

    topic = normalize_event_topic(event_topic)
    hydrated = copy.deepcopy(payload)
    if service not in _EVENT_TOPIC_SERVICES:
        return hydrated
    event_topics = selected.get("event_topics")
    if not isinstance(event_topics, dict) or not isinstance(event_topics.get("events"), str):
        raise EventTopicError("selected service tfvars must contain event_topics.events")
    hydrated["environments"][environment][service]["event_topics"]["events"] = topic
    return hydrated


def main() -> int:
    """Read tfvars from stdin and emit the event-topic-hydrated payload to stdout."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--event-topic", required=True)
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
        )
        json.dump(hydrated, sys.stdout, separators=(",", ":"), sort_keys=True)
        sys.stdout.write("\n")
    except (json.JSONDecodeError, ServiceContractError, EventTopicError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
