"""Local smoke publisher - send one test event to Event Hubs Kafka.

Uses the user's `az account get-access-token` to authenticate via
OAUTHBEARER. Run once after a deploy to verify the consumer picks up
the round-trip end-to-end.

    export FDAI_EVENT_HUB_NAMESPACE=<caf-ns>.servicebus.windows.net
    uv run python tools/publish_smoke_event.py --idempotency-key smoke-2

Env vars:

- ``FDAI_EVENT_HUB_NAMESPACE`` (**required**) - fully qualified Event Hubs
  namespace host, e.g. ``evhns-fdai-dev-krc.servicebus.windows.net``.
  Never hardcoded here per generic-scope.instructions.md (no endpoints in
  the repo); every environment / region has a different value.
- ``FDAI_EVENT_HUB_TOPIC`` (optional, default ``aw.change.events``) -
  Kafka topic to publish to. The default is the change-event topic every
  FDAI deployment provisions; a fork can point at a custom topic.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import ssl
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

from aiokafka import AIOKafkaProducer
from aiokafka.abc import AbstractTokenProvider

_DEFAULT_TOPIC = "aw.change.events"


def _resolve_namespace() -> str:
    """Return the Event Hubs namespace host from env; fail loud if unset.

    Deliberately no default - a hardcoded namespace would leak an
    environment identifier into the repo (generic-scope violation) and
    would silently target the wrong deployment when an operator runs
    the smoke tool from the wrong shell.
    """
    ns = os.environ.get("FDAI_EVENT_HUB_NAMESPACE", "").strip()
    if not ns:
        raise SystemExit(
            "publish_smoke_event: FDAI_EVENT_HUB_NAMESPACE is not set. "
            "Export the fully qualified Event Hubs namespace host, e.g.:\n"
            "  export FDAI_EVENT_HUB_NAMESPACE='<caf-ns>.servicebus.windows.net'"
        )
    return ns


class _AzCliTokenProvider(AbstractTokenProvider):  # type: ignore[misc]
    def __init__(self, namespace: str) -> None:
        self._namespace = namespace

    async def token(self) -> str:
        proc = await asyncio.create_subprocess_exec(
            "az",
            "account",
            "get-access-token",
            "--resource",
            f"https://{self._namespace}",
            "--query",
            "accessToken",
            "--output",
            "tsv",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"az CLI failed: {err.decode()}")
        return out.decode().strip()


def _build_event(*, idempotency_key: str) -> dict[str, Any]:
    now = datetime.now(tz=UTC).isoformat()
    return {
        "schema_version": "1.0.0",
        "event_id": str(uuid.uuid4()),
        "idempotency_key": idempotency_key,
        "source": "smoke-tool",
        "event_type": "resource.created",
        "detected_at": now,
        "ingested_at": now,
        "mode": "shadow",
        "resource_ref": "resource:example/rg-a/sa-x",
        "payload": {
            "resource": {
                "resource_id": "resource:example/rg-a/sa-x",
                "type": "object-storage",
                "props": {
                    "public_access": True,
                    "https_only": True,
                    "min_tls_version": "TLS1_2",
                },
            }
        },
    }


async def _main(idempotency_key: str) -> int:
    namespace = _resolve_namespace()
    topic = os.environ.get("FDAI_EVENT_HUB_TOPIC", _DEFAULT_TOPIC).strip() or _DEFAULT_TOPIC
    bootstrap = f"{namespace}:9093"
    payload = _build_event(idempotency_key=idempotency_key)
    producer = AIOKafkaProducer(
        bootstrap_servers=bootstrap,
        security_protocol="SASL_SSL",
        sasl_mechanism="OAUTHBEARER",
        sasl_oauth_token_provider=_AzCliTokenProvider(namespace),
        ssl_context=ssl.create_default_context(),
        api_version="2.0.0",
        enable_idempotence=True,
        acks="all",
    )
    await producer.start()
    try:
        meta = await producer.send_and_wait(
            topic,
            value=json.dumps(payload, sort_keys=True).encode("utf-8"),
            key=idempotency_key.encode("utf-8"),
        )
        print(f"published: topic={meta.topic} partition={meta.partition} offset={meta.offset}")
    finally:
        await producer.stop()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--idempotency-key", default="smoke-2")
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.idempotency_key)))
