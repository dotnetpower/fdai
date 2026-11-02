#!/usr/bin/env python3
"""Rehearse and verify the complete System Knowledge Outgoing Webhook rollout lifecycle."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import importlib.util
import json
import time
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
from azure.core.exceptions import (
    ResourceExistsError,
    ResourceModifiedError,
    ResourceNotFoundError,
)
from fdai_service_contracts.ontology_query import content_digest
from fdai_system_knowledge_service.application import create_app, create_runtime
from fdai_system_knowledge_service.blob_ledger import AzureBlobMessageLedger
from fdai_system_knowledge_service.catalog import load_catalog
from fdai_system_knowledge_service.config import SystemKnowledgeSettings
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CATALOG_PATH = (
    ROOT / "services/system-knowledge-service/src/fdai_system_knowledge_service/data/catalog.json"
)
PREPARE_PATH = ROOT / "scripts/deployment/system_knowledge/prepare_deployment.py"
GUARD_PATH = ROOT / "scripts/deployment/system_knowledge/guard_plan.py"
MATERIALIZE_PATH = ROOT / "scripts/deployment/azure/materialize_system_knowledge_secret.py"
PREFIX = "module.system_knowledge_service[0]."


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load helper module {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _StoredBlob:
    def __init__(self, *, body: bytes, etag: int) -> None:
        self.body = body
        self.etag = etag


class _BlobDownload:
    def __init__(self, stored: _StoredBlob) -> None:
        self._stored = stored
        self.properties = SimpleNamespace(etag=str(stored.etag))

    async def readall(self) -> bytes:
        return self._stored.body


class _InMemoryBlobClient:
    def __init__(self, container: _InMemoryBlobContainer, name: str) -> None:
        self._container = container
        self._name = name

    async def upload_blob(self, data: bytes, **kwargs: Any) -> None:
        current = self._container.records.get(self._name)
        if current is not None and kwargs.get("overwrite") is False:
            raise ResourceExistsError("claim blob already exists")
        etag = kwargs.get("etag")
        if current is not None and etag is not None and str(current.etag) != etag:
            raise ResourceModifiedError("claim blob etag changed")
        self._container.records[self._name] = _StoredBlob(
            body=data,
            etag=1 if current is None else current.etag + 1,
        )

    async def download_blob(self) -> _BlobDownload:
        try:
            return _BlobDownload(self._container.records[self._name])
        except KeyError as exc:
            raise ResourceNotFoundError("claim blob not found") from exc

    async def delete_blob(self, **kwargs: Any) -> None:
        try:
            current = self._container.records[self._name]
        except KeyError as exc:
            raise ResourceNotFoundError("claim blob not found") from exc
        if str(current.etag) != kwargs.get("etag"):
            raise ResourceModifiedError("claim blob etag changed")
        del self._container.records[self._name]


class _InMemoryBlobContainer:
    """In-memory Azure Blob CAS container for deterministic deployed-venue verification."""

    def __init__(self) -> None:
        self.records: dict[str, _StoredBlob] = {}
        self.probed_count = 0
        self.closed_count = 0

    async def _properties(self) -> dict[str, object]:
        self.probed_count += 1
        return {"container": "system-knowledge-claims", "public_access": None}

    def get_container_properties(self, **_kwargs: Any) -> Any:
        return self._properties()

    async def _items(self, prefix: str) -> AsyncIterator[SimpleNamespace]:
        for name in sorted(self.records):
            if name.startswith(prefix):
                yield SimpleNamespace(name=name)

    def list_blobs(
        self,
        name_starts_with: str | None = None,
        include: Any = None,
        **_kwargs: Any,
    ) -> AsyncIterator[SimpleNamespace]:
        del include
        return self._items(name_starts_with or "")

    def get_blob_client(
        self,
        blob: str,
        snapshot: str | None = None,
        *,
        version_id: str | None = None,
    ) -> _InMemoryBlobClient:
        del snapshot, version_id
        return _InMemoryBlobClient(self, blob)

    async def _close(self) -> None:
        self.closed_count += 1

    def close(self) -> Any:
        return self._close()


class _NoOpCredential:
    def __init__(self) -> None:
        self.closed_count = 0

    async def close(self) -> None:
        self.closed_count += 1


def _build_outgoing_plan(
    *,
    tfvars: Mapping[str, Any],
    transition: str,
) -> dict[str, list[dict[str, object]]]:
    """Synthesize the exact Terraform plan projection for one Outgoing Webhook transition."""

    image_ref = str(tfvars["image"])
    env_names = {
        "FDAI_EXECUTION_VENUE",
        "FDAI_SYSTEM_KNOWLEDGE_CLAIM_CONTAINER_URL",
        "FDAI_SYSTEM_KNOWLEDGE_MI_CLIENT_ID",
        "FDAI_SYSTEM_KNOWLEDGE_SOURCE_REVISION",
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_CHANNEL_IDS_JSON",
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_PRINCIPAL_MAP_JSON",
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TEAM_IDS_JSON",
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TENANT_ID",
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TRANSPORT",
        "RUNTIME_ENV",
    }
    if transition == "enable":
        env_names.add("FDAI_SYSTEM_KNOWLEDGE_TEAMS_OUTGOING_HMAC_SECRET")
    actions = ["delete"] if transition == "disable" else ["create"]
    environment = [{"name": name, "value": "redacted"} for name in sorted(env_names)]
    role_resources: list[dict[str, object]] = [
        {
            "address": PREFIX + f"azurerm_role_assignment.{name}",
            "change": {
                "actions": actions,
                "after": {"role_definition_name": role},
            },
        }
        for name, role in (
            ("acr_pull", "AcrPull"),
            ("claim_writer", "Storage Blob Data Contributor"),
            ("principal_map_reader", "Key Vault Secrets User"),
        )
    ]
    resources: list[dict[str, object]] = [
        {
            "address": PREFIX + "azurerm_user_assigned_identity.service",
            "change": {"actions": actions, "after": {}},
        },
        {
            "address": PREFIX + "azurerm_storage_container.claims",
            "change": {
                "actions": actions,
                "after": {"container_access_type": "private"},
            },
        },
        *role_resources,
        {
            "address": PREFIX + "module.container_app.azurerm_container_app.service",
            "change": {
                "actions": actions,
                "after": {
                    "name": tfvars["name"],
                    "identity": [{"identity_ids": ["id-fdai-knowledge-dev"]}],
                    "template": [
                        {
                            "min_replicas": 1,
                            "max_replicas": 1,
                            "container": [
                                {
                                    "name": "system-knowledge-service",
                                    "image": image_ref,
                                    "env": environment,
                                }
                            ],
                        }
                    ],
                },
            },
        },
        {
            "address": PREFIX + "terraform_data.authority_contract",
            "change": {
                "actions": actions,
                "after": {
                    "input": {
                        "execution_authority": False,
                        "replica_ceiling": 1,
                        "teams_transport": "outgoing_webhook",
                    }
                },
            },
        },
    ]
    return {"resource_changes": resources}


def _signed_activity(
    *,
    signing_key: bytes,
    message_id: str,
    text: str,
    received_at: datetime,
) -> tuple[bytes, str]:
    body = json.dumps(
        {
            "type": "message",
            "id": message_id,
            "timestamp": received_at.isoformat(),
            "channelId": "msteams",
            "locale": "en-US",
            "conversation": {
                "id": "19:channel-example@thread.tacv2;messageid=" + message_id,
                "conversationType": "channel",
                "tenantId": "00000000-0000-0000-0000-000000000002",
            },
            "recipient": {"id": "outgoing-webhook-fdai-bot"},
            "from": {"aadObjectId": "00000000-0000-0000-0000-000000000010"},
            "channelData": {
                "tenant": {"id": "00000000-0000-0000-0000-000000000002"},
                "team": {"id": "00000000-0000-0000-0000-000000000020"},
                "channel": {"id": "19:channel-example@thread.tacv2"},
            },
            "text": text,
            "entities": [
                {
                    "type": "mention",
                    "text": "<at>FDAI-bot</at>",
                    "mentioned": {
                        "id": "outgoing-webhook-fdai-bot",
                        "name": "FDAI-bot",
                    },
                }
            ],
        },
        separators=(",", ":"),
    ).encode("utf-8")
    signature = base64.b64encode(hmac.new(signing_key, body, hashlib.sha256).digest()).decode(
        "ascii"
    )
    return body, f"HMAC {signature}"


async def rehearse_outgoing_webhook_rollout(*, image_ref: str) -> dict[str, object]:
    """Execute the Outgoing Webhook bootstrap, enable, mention, restart, cost, and disable flow."""

    prepare = _load_module(PREPARE_PATH, "prepare_system_knowledge_rehearsal")
    guard = _load_module(GUARD_PATH, "guard_system_knowledge_rehearsal")
    materialize_mod = _load_module(MATERIALIZE_PATH, "materialize_system_knowledge_rehearsal")

    catalog = load_catalog(DEFAULT_CATALOG_PATH)
    source_revision = catalog.source_revision

    platform_outputs = {
        "resource_group_name": {"value": "rg-example"},
        "container_app_environment_id": {
            "value": (
                "/subscriptions/00000000-0000-0000-0000-000000000001/"
                "resourceGroups/rg-example/providers/Microsoft.App/managedEnvironments/cae-example"
            )
        },
        "container_registry_name": {"value": "crexample"},
        "container_registry_login_server": {"value": "crexample.azurecr.io"},
        "key_vault_uri": {"value": "https://kv-example.vault.azure.net/"},
        "document_storage_account_name": {"value": "stexample"},
    }
    teams_profile_json = json.dumps(
        {
            "transport": "outgoing_webhook",
            "service_name": "ca-fdai-knowledge-dev",
            "tenant_id": "00000000-0000-0000-0000-000000000002",
            "team_ids": ["00000000-0000-0000-0000-000000000020"],
            "channel_ids": ["19:channel-example@thread.tacv2"],
        }
    )
    principal_map_json = '{"00000000-0000-0000-0000-000000000010":"knowledge-reader-example"}'
    signing_key = hashlib.sha256(b"fdai-system-knowledge-rehearsal-key").digest()
    hmac_secret_b64 = base64.b64encode(signing_key).decode("ascii")

    # 1. Bootstrap plan and fail-closed runtime before HMAC binding
    bootstrap_tfvars, bootstrap_context = prepare.build_inputs(
        platform_outputs=platform_outputs,
        teams_profile_json=teams_profile_json,
        principal_map_json=principal_map_json,
        subscription_id="00000000-0000-0000-0000-000000000001",
        region="westus3",
        environment="dev",
        image_ref=image_ref,
        previous_image_ref=image_ref,
        source_revision=source_revision,
        transition="bootstrap",
    )
    bootstrap_plan = _build_outgoing_plan(tfvars=bootstrap_tfvars, transition="bootstrap")
    guard.validate_plan(
        bootstrap_plan,
        transition="bootstrap",
        image_ref=image_ref,
        transport="outgoing_webhook",
    )

    blob_container = _InMemoryBlobContainer()
    base_env = {
        "FDAI_EXECUTION_VENUE": "deployed",
        "RUNTIME_ENV": "dev",
        "FDAI_SYSTEM_KNOWLEDGE_MI_CLIENT_ID": "00000000-0000-0000-0000-000000000003",
        "FDAI_SYSTEM_KNOWLEDGE_SOURCE_REVISION": source_revision,
        "FDAI_SYSTEM_KNOWLEDGE_CLAIM_CONTAINER_URL": (
            "https://stexample.blob.core.windows.net/system-knowledge-claims"
        ),
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TRANSPORT": "outgoing_webhook",
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TENANT_ID": "00000000-0000-0000-0000-000000000002",
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TEAM_IDS_JSON": '["00000000-0000-0000-0000-000000000020"]',
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_CHANNEL_IDS_JSON": '["19:channel-example@thread.tacv2"]',
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_PRINCIPAL_MAP_JSON": principal_map_json,
    }
    bootstrap_settings = SystemKnowledgeSettings.parse(base_env)
    bootstrap_runtime = create_runtime(
        bootstrap_settings,
        blob_container=blob_container,
        blob_credential=_NoOpCredential(),
    )
    bootstrap_app = create_app(runtime=bootstrap_runtime)
    now = datetime.now(UTC)
    first_body, first_auth = _signed_activity(
        signing_key=signing_key,
        message_id="msg-001",
        text="<at>FDAI-bot</at> How does FDAI keep actions safe?",
        received_at=now,
    )
    async with bootstrap_app.router.lifespan_context(bootstrap_app):
        async with AsyncClient(
            transport=ASGITransport(app=bootstrap_app),
            base_url="http://test",
        ) as client:
            boot_ready = await client.get("/health/ready")
            boot_webhook = await client.post(
                "/api/teams/outgoing-webhook",
                content=first_body,
                headers={"content-type": "application/json", "authorization": first_auth},
            )
    if boot_ready.status_code != 200 or boot_webhook.status_code != 503:
        raise RuntimeError("bootstrap endpoint did not fail closed with 503 before HMAC binding")

    # 2. Protected Key Vault secret materialization & readback + Enable plan
    vault_store: dict[str, str] = {}

    def kv_handler(request: httpx.Request) -> httpx.Response:
        secret_path = request.url.path
        if request.method == "PUT":
            payload = json.loads(request.content.decode("utf-8"))
            vault_store[secret_path] = payload["value"]
            return httpx.Response(200, json={"id": str(request.url)})
        return httpx.Response(200, json={"value": vault_store[secret_path]})

    canonical_map = materialize_mod.validate_principal_map(principal_map_json)
    validated_hmac = materialize_mod.validate_outgoing_hmac(hmac_secret_b64)
    with httpx.Client(transport=httpx.MockTransport(kv_handler)) as kv_client:
        materialize_mod.materialize(
            vault_uri="https://kv-example.vault.azure.net",
            principal_map=canonical_map,
            access_token="token-example",  # noqa: S106 - synthetic in-memory rehearsal token
            transport=kv_client,
        )
        materialize_mod.materialize_outgoing_hmac(
            vault_uri="https://kv-example.vault.azure.net",
            hmac_secret=validated_hmac,
            access_token="token-example",  # noqa: S106 - synthetic in-memory rehearsal token
            transport=kv_client,
        )

    enable_tfvars, enable_context = prepare.build_inputs(
        platform_outputs=platform_outputs,
        teams_profile_json=teams_profile_json,
        principal_map_json=principal_map_json,
        subscription_id="00000000-0000-0000-0000-000000000001",
        region="westus3",
        environment="dev",
        image_ref=image_ref,
        previous_image_ref=image_ref,
        source_revision=source_revision,
        transition="enable",
        outgoing_hmac_secret=validated_hmac,
    )
    enable_plan = _build_outgoing_plan(tfvars=enable_tfvars, transition="enable")
    guard.validate_plan(
        enable_plan,
        transition="enable",
        image_ref=image_ref,
        transport="outgoing_webhook",
    )

    # 3. Live mention reply and replay deduplication on deployed Blob CAS ledger
    enabled_env = {
        **base_env,
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_OUTGOING_HMAC_SECRET": validated_hmac,
    }
    enabled_runtime = create_runtime(
        SystemKnowledgeSettings.parse(enabled_env),
        blob_container=blob_container,
        blob_credential=_NoOpCredential(),
    )
    enabled_app = create_app(runtime=enabled_runtime)
    async with enabled_app.router.lifespan_context(enabled_app):
        async with AsyncClient(
            transport=ASGITransport(app=enabled_app),
            base_url="http://test",
        ) as client:
            first_reply = await client.post(
                "/api/teams/outgoing-webhook",
                content=first_body,
                headers={"content-type": "application/json", "authorization": first_auth},
            )
            blobs_after_first = {k: v.etag for k, v in blob_container.records.items()}
            replay_reply = await client.post(
                "/api/teams/outgoing-webhook",
                content=first_body,
                headers={"content-type": "application/json", "authorization": first_auth},
            )
            blobs_after_replay = {k: v.etag for k, v in blob_container.records.items()}

    first_json = first_reply.json()
    if (
        first_reply.status_code != 200
        or first_reply.headers.get("x-fdai-claim-state") != "responded"
        or replay_reply.status_code != 200
        or replay_reply.headers.get("x-fdai-claim-state") != "duplicate"
        or replay_reply.json() != first_json
        or blobs_after_first != blobs_after_replay
        or "`execution_authority=false`" not in first_json.get("text", "")
    ):
        raise RuntimeError("mention reply or replay deduplication verification failed")

    # 4. Exact-revision restart preserving delivered and ambiguous claim behavior
    ambiguous_body, ambiguous_auth = _signed_activity(
        signing_key=signing_key,
        message_id="msg-002-interrupted-send",
        text="<at>FDAI-bot</at> What is the seven-safeguard execution boundary?",
        received_at=now,
    )
    processing_body, processing_auth = _signed_activity(
        signing_key=signing_key,
        message_id="msg-003-interrupted-processing",
        text="<at>FDAI-bot</at> How does audit chain tamper evidence work?",
        received_at=now,
    )
    ambiguous_key = content_digest(
        {
            "channel": "msteams",
            "conversation_id": (
                "19:channel-example@thread.tacv2;messageid=msg-002-interrupted-send"
            ),
            "message_id": "msg-002-interrupted-send",
        }
    )
    processing_key = content_digest(
        {
            "channel": "msteams",
            "conversation_id": (
                "19:channel-example@thread.tacv2;messageid=msg-003-interrupted-processing"
            ),
            "message_id": "msg-003-interrupted-processing",
        }
    )
    seed_ledger = AzureBlobMessageLedger(
        container=blob_container,
        credential=_NoOpCredential(),
    )
    if not await seed_ledger.claim(ambiguous_key):
        raise RuntimeError("unable to seed interrupted sending claim")
    await seed_ledger.mark_sending(ambiguous_key, "sha256:" + ("d" * 64))
    if not await seed_ledger.claim(processing_key):
        raise RuntimeError("unable to seed interrupted processing claim")

    restarted_runtime = create_runtime(
        SystemKnowledgeSettings.parse(enabled_env),
        blob_container=blob_container,
        blob_credential=_NoOpCredential(),
    )
    restarted_app = create_app(runtime=restarted_runtime)
    async with restarted_app.router.lifespan_context(restarted_app):
        async with AsyncClient(
            transport=ASGITransport(app=restarted_app),
            base_url="http://test",
        ) as client:
            after_restart_delivered = await client.post(
                "/api/teams/outgoing-webhook",
                content=first_body,
                headers={"content-type": "application/json", "authorization": first_auth},
            )
            after_restart_ambiguous = await client.post(
                "/api/teams/outgoing-webhook",
                content=ambiguous_body,
                headers={"content-type": "application/json", "authorization": ambiguous_auth},
            )
            after_restart_recovered = await client.post(
                "/api/teams/outgoing-webhook",
                content=processing_body,
                headers={"content-type": "application/json", "authorization": processing_auth},
            )

    if (
        after_restart_delivered.headers.get("x-fdai-claim-state") != "duplicate"
        or after_restart_ambiguous.headers.get("x-fdai-claim-state") != "ambiguous"
        or after_restart_recovered.headers.get("x-fdai-claim-state") != "responded"
    ):
        raise RuntimeError("restart claim preservation verification failed")

    # 5. Disable transition (< 15 minutes) and target-state restoration
    disable_started = time.monotonic()
    disable_tfvars, disable_context = prepare.build_inputs(
        platform_outputs=platform_outputs,
        teams_profile_json=teams_profile_json,
        principal_map_json=principal_map_json,
        subscription_id="00000000-0000-0000-0000-000000000001",
        region="westus3",
        environment="dev",
        image_ref=image_ref,
        previous_image_ref=image_ref,
        source_revision=source_revision,
        transition="disable",
    )
    disable_plan = _build_outgoing_plan(tfvars=disable_tfvars, transition="disable")
    guard.validate_plan(
        disable_plan,
        transition="disable",
        image_ref=image_ref,
        transport="outgoing_webhook",
    )
    disable_elapsed = round(time.monotonic() - disable_started, 4)
    disable_receipt = guard.validate_disable_rollback(
        outputs={
            "service": {"value": None},
            "identity": {"value": None},
            "bot": {"value": None},
            "claim_store": {"value": None},
        },
        state_addresses=[],
        elapsed_seconds=disable_elapsed,
    )

    restore_tfvars, restore_context = prepare.build_inputs(
        platform_outputs=platform_outputs,
        teams_profile_json=teams_profile_json,
        principal_map_json=principal_map_json,
        subscription_id="00000000-0000-0000-0000-000000000001",
        region="westus3",
        environment="dev",
        image_ref=image_ref,
        previous_image_ref=image_ref,
        source_revision=source_revision,
        transition="enable",
        outgoing_hmac_secret=validated_hmac,
    )
    restore_plan = _build_outgoing_plan(tfvars=restore_tfvars, transition="enable")
    guard.validate_plan(
        restore_plan,
        transition="enable",
        image_ref=image_ref,
        transport="outgoing_webhook",
    )

    return {
        "schema_version": "fdai.system-knowledge-rollout-rehearsal.v1",
        "catalog_source_revision": source_revision,
        "catalog_record_count": len(catalog.records),
        "image_ref": image_ref,
        "image_digest": image_ref.rsplit("@", 1)[1],
        "transitions": {
            "bootstrap": {
                "context_digest": bootstrap_context["context_digest"],
                "resource_count": len(bootstrap_plan["resource_changes"]),
                "azure_bot_resources": 0,
                "unconfigured_webhook_http_status": boot_webhook.status_code,
            },
            "enable": {
                "context_digest": enable_context["context_digest"],
                "resource_count": len(enable_plan["resource_changes"]),
                "azure_bot_resources": 0,
                "key_vault_secrets_materialized": len(vault_store),
            },
            "mention_and_replay": {
                "first_http_status": first_reply.status_code,
                "first_claim_state": first_reply.headers.get("x-fdai-claim-state"),
                "replay_http_status": replay_reply.status_code,
                "replay_claim_state": replay_reply.headers.get("x-fdai-claim-state"),
                "duplicate_blob_writes": 0,
                "execution_authority": False,
            },
            "restart_recovery": {
                "delivered_claim_after_restart": after_restart_delivered.headers.get(
                    "x-fdai-claim-state"
                ),
                "ambiguous_claim_after_restart": after_restart_ambiguous.headers.get(
                    "x-fdai-claim-state"
                ),
                "interrupted_processing_after_restart": after_restart_recovered.headers.get(
                    "x-fdai-claim-state"
                ),
            },
            "incremental_cost": enable_context["incremental_cost"],
            "disable": {
                "context_digest": disable_context["context_digest"],
                **disable_receipt,
            },
            "restore": {
                "context_digest": restore_context["context_digest"],
                "restored_enabled": restore_tfvars["enabled"],
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image-ref",
        default="crexample.azurecr.io/fdai-system-knowledge-service@sha256:" + ("a" * 64),
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    receipt = asyncio.run(rehearse_outgoing_webhook_rollout(image_ref=args.image_ref))
    rendered = json.dumps(receipt, indent=2, sort_keys=True)
    if args.output is not None:
        prepare = _load_module(PREPARE_PATH, "prepare_system_knowledge_rehearsal_write")
        prepare.write_private_json(args.output, receipt)
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
