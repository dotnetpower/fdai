"""Local smoke publisher — send one test event to Event Hubs Kafka.

Uses the user's `az account get-access-token` to authenticate via
OAUTHBEARER. Run once after a deploy to verify the consumer picks up
the round-trip end-to-end.

    uv run python tools/publish_smoke_event.py --idempotency-key smoke-2
"""

from __future__ import annotations

import argparse
import asyncio
import json
import ssl
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

from aiokafka import AIOKafkaProducer
from aiokafka.abc import AbstractTokenProvider

NAMESPACE = "evhns-aiopspilot-dev-krc.servicebus.windows.net"
BOOTSTRAP = f"{NAMESPACE}:9093"
TOPIC = "aw.change.events"


class _AzCliTokenProvider(AbstractTokenProvider):  # type: ignore[misc]
    async def token(self) -> str:
        proc = await asyncio.create_subprocess_exec(
            "az",
            "account",
            "get-access-token",
            "--resource",
            f"https://{NAMESPACE}",
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
    payload = _build_event(idempotency_key=idempotency_key)
    producer = AIOKafkaProducer(
        bootstrap_servers=BOOTSTRAP,
        security_protocol="SASL_SSL",
        sasl_mechanism="OAUTHBEARER",
        sasl_oauth_token_provider=_AzCliTokenProvider(),
        ssl_context=ssl.create_default_context(),
        api_version="2.0.0",
        enable_idempotence=True,
        acks="all",
    )
    await producer.start()
    try:
        meta = await producer.send_and_wait(
            TOPIC,
            value=json.dumps(payload, sort_keys=True).encode("utf-8"),
            key=idempotency_key.encode("utf-8"),
        )
        print(
            f"published: topic={meta.topic} partition={meta.partition} offset={meta.offset}"
        )
    finally:
        await producer.stop()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--idempotency-key", default="smoke-2")
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.idempotency_key)))
