"""Build one closed, private Hub-managed installation input set."""

from __future__ import annotations

import base64
import re
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest, load_json_object
from fdai_deployment_cli.lifecycle_native import NativeApproval, NativeScope
from fdai_deployment_cli.lifecycle_release import (
    APPLICATION_COMPONENT_RELEASE_SCHEMA,
    ApplicationRelease,
    parse_lifecycle_release_manifest,
)
from fdai_deployment_cli.private_output import (
    read_private_bytes,
    write_private_bytes,
)
from fdai_deployment_cli.runtime_release import is_release_id
from fdai_deployment_cli.source_input import inspect_source
from fdai_lifecycle_agent.cli import LOCAL_POLICY_SCHEMA, load_local_policy
from fdai_lifecycle_agent.runtime_bundle import RuntimeBundle
from fdai_lifecycle_agent.signatures import load_ed25519_public_key
from fdai_lifecycle_agent.workload import is_repository
from fdai_lifecycle_hub import schemas
from fdai_lifecycle_hub.domain import (
    Configuration,
    DailyWindow,
    EntityState,
    Health,
    ReportedState,
    Settings,
)
from fdai_lifecycle_hub.execution_settings import (
    ApplicationBindingRequest,
    settings_digest,
)
from fdai_lifecycle_hub.signing import key_id_for, raw_public_key, verify_key_proof
from pydantic import BaseModel, ConfigDict, Field

_IMAGE = re.compile(r"(?P<repository>[^@]+)@(?P<digest>sha256:[0-9a-f]{64})\Z", re.ASCII)


class PreparationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: str
    installation_id: str
    entity_id: str
    product: str
    release_id: str
    source_commit: str
    release_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    configuration_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_bundle_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    native_scope_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    settings_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    bound_settings_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    hub_key_id: str
    image_digests: tuple[str, ...]
    destination: str
    mutation_performed: bool
    deployment_ready: bool


class EnrollmentRefreshReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: str
    installation_id: str
    installation_key_id: str
    requested_at: datetime
    destination: str
    mutation_performed: bool


def prepare_installation(
    *,
    source_root: Path,
    destination: Path,
    runtime_bundle_path: Path,
    component_images_path: Path,
    hub_public_key_path: Path,
    release_public_key_path: Path,
    installation_id: str,
    entity_id: str,
    product: str,
    release_id: str,
    channel: str,
    region: str,
    actor: str,
    now: datetime,
) -> PreparationReceipt:
    """Create private, signed inputs without contacting a Hub, cluster, registry, or Azure."""

    if not is_release_id(release_id) or now.tzinfo is None:
        raise ValueError("Release id and preparation time are invalid.")
    source = inspect_source(source_root)
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("Lifecycle preparation destination must not exist.")
    destination.mkdir(mode=0o700, parents=True)
    try:
        runtime_raw = read_private_bytes(
            runtime_bundle_path.absolute(),
            max_bytes=64 * 1024,
        )
        runtime_bundle = RuntimeBundle.model_validate_json(runtime_raw)
        if runtime_bundle.product != product:
            raise ValueError("Runtime bundle product differs.")
        entity_ids = {item.entity_id for item in runtime_bundle.objects}
        if entity_ids != {entity_id}:
            raise ValueError("Initial managed preparation requires one exact runtime Entity.")
        images = _component_images(component_images_path, runtime_bundle, entity_id)
        repositories = {name: value.rsplit("@", 1)[0] for name, value in images.items()}
        digests = {name: value.rsplit("@", 1)[1] for name, value in images.items()}

        schema = _configuration_schema(release_id, runtime_bundle.digest)
        schema_keys = schema["keys"]
        if not isinstance(schema_keys, dict):
            raise TypeError("Prepared configuration schema keys are invalid.")
        release_document = {
            "schema_version": APPLICATION_COMPONENT_RELEASE_SCHEMA,
            "product": product,
            "release_version": release_id,
            "source_commit": source.commit,
            "platform_tag": "linux-x86_64",
            "components": {
                name: {"image_digest": digest} for name, digest in sorted(digests.items())
            },
            "configuration_schema": schema,
        }
        parsed_release = parse_lifecycle_release_manifest(canonical_bytes(release_document))
        if not isinstance(parsed_release, ApplicationRelease):
            raise ValueError("Prepared Release is not an application component Release.")

        version_range = _major_range(release_id)
        configuration = Configuration(
            schema=schema_keys,
            environment={},
            entity_overrides=({"versions": version_range, "values": {}},),
        )
        configuration_document = {
            "schema": configuration.schema,
            "environment": configuration.environment,
            "entity_overrides": list(configuration.entity_overrides),
        }
        configuration_bytes = canonical_bytes(configuration_document)
        configuration_key = Ed25519PrivateKey.generate()
        configuration_signature = configuration_key.sign(configuration_bytes)
        installation_key = Ed25519PrivateKey.generate()

        settings = Settings(
            channel=channel,
            version_range=version_range,
            region=region,
            allowed_regions=frozenset({region}),
            windows=(
                DailyWindow(time(0), timedelta(days=1), "UTC"),
                DailyWindow(time(12), timedelta(days=1), "UTC"),
            ),
        )
        state_content = {
            "schema_revision": parsed_release.schema_target,
            "entities": {
                entity_id: {
                    "release_id": None,
                    "artifact_digests": [],
                    "health": Health.UNKNOWN.value,
                }
            },
            "observed_at": now.astimezone(UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "available_artifact_digests": sorted(digests.values()),
        }
        state = ReportedState(
            digest=canonical_digest(state_content),
            schema_revision=parsed_release.schema_target,
            entities={
                entity_id: EntityState(
                    release_id=None,
                    artifact_digests=frozenset(),
                    health=Health.UNKNOWN,
                )
            },
            observed_at=now,
            available_artifact_digests=frozenset(digests.values()),
        )
        enrollment_template = {
            "installation_id": installation_id,
            "settings": schemas.settings_json.dump_python(settings, mode="json"),
            "configuration": schemas.configuration_json.dump_python(
                configuration,
                mode="json",
            ),
            "entities": [{"entity_id": entity_id, "kind": "native-workload-scope"}],
            "reported": schemas.reported_state_json.dump_python(state, mode="json"),
        }
        enrollment = schemas.sign_enrollment(enrollment_template, installation_key, now)
        signed_enrollment = schemas.SignedEnrollment.model_validate(
            {
                "signed_payload": base64.b64encode(enrollment.signed_payload).decode("ascii"),
                "proof": base64.b64encode(enrollment.proof).decode("ascii"),
            }
        )

        deployments = tuple(
            sorted(item.name for item in runtime_bundle.objects if item.kind == "Deployment")
        )
        services = tuple(
            sorted(item.name for item in runtime_bundle.objects if item.kind == "Service")
        )
        schedules = tuple(
            sorted(item.name for item in runtime_bundle.objects if item.kind == "CronJob")
        )
        native_scope = NativeScope(
            installation_id=installation_id,
            entity_id=entity_id,
            product=product,
            namespace=runtime_bundle.namespace,
            components=deployments,
            service_components=services,
            scheduled_components=schedules,
        )
        approval = NativeApproval(
            schema_version="fdai.lifecycle-native-approval.v1",
            scope=native_scope,
            profile="full-authority-development",
            approved_by=actor,
            approved_at=now,
            expires_at=now + timedelta(hours=4),
        )
        local_policy = {
            "schema": LOCAL_POLICY_SCHEMA,
            "entity_ids": [entity_id],
            "regions": [region],
            "capability_modes": {},
            "destructive_allowed": False,
            "max_duration_minutes": 60,
            "entity_components": {entity_id: sorted(images)},
            "component_images": repositories,
            "product": product,
            "native_scope_digest": native_scope.digest,
            "runtime_bundle": runtime_bundle.model_dump(mode="json"),
        }

        hub_public = load_ed25519_public_key(hub_public_key_path)
        release_public = load_ed25519_public_key(release_public_key_path)
        _write_key_pair(destination, "installation", installation_key)
        _write_key_pair(destination, "configuration", configuration_key)
        _write_public_key(destination / "hub-public.pem", hub_public)
        _write_public_key(destination / "release-public.pem", release_public)
        _write_json(destination / "release.json", release_document)
        _write_json(
            destination / "release-publication-request.json",
            {
                "schema_version": "fdai.release-publication-request.v1",
                "request_id": str(uuid4()),
                "release_id": release_id,
                "manifest": canonical_bytes(release_document).decode(),
                "manifest_digest": parsed_release.digest,
                "channels": [channel],
                "reason": "Approved Hub-managed development publication",
                "confirmation": f"publish {release_id} to {channel}",
            },
        )
        _write_json(
            destination / "signed-enrollment.json",
            signed_enrollment.model_dump(mode="json"),
        )
        _write_json(destination / "configuration.json", configuration_document)
        write_private_bytes(destination / "configuration.sig", configuration_signature)
        cache = destination / "artifact-cache/configurations"
        cache.mkdir(mode=0o700, parents=True)
        write_private_bytes(cache / f"{configuration.digest}.json", configuration_bytes)
        write_private_bytes(cache / f"{configuration.digest}.sig", configuration_signature)
        _write_json(
            destination / "application-binding.json",
            ApplicationBindingRequest(
                request_id=uuid4(),
                expected_settings_digest=settings_digest(settings),
                reason_code="hub_managed_bootstrap",
                confirmation=(
                    f"bind application {installation_id} {product} {settings_digest(settings)}"
                ),
                product=product,
            ).model_dump(mode="json"),
        )
        _write_json(
            destination / "entity-settings.json",
            {"overrides": [{"versions": version_range, "values": {}}]},
        )
        _write_json(
            destination / "current-state.json",
            schemas.reported_state_json.dump_python(state, mode="json"),
        )
        _write_json(destination / "local-policy.json", local_policy)
        _write_json(destination / "native-approval.json", approval.model_dump(mode="json"))
        _write_json(destination / "runtime-bundle.json", runtime_bundle.model_dump(mode="json"))
        receipt = PreparationReceipt(
            schema_version="fdai.hub-managed-preparation.v1",
            installation_id=installation_id,
            entity_id=entity_id,
            product=product,
            release_id=release_id,
            source_commit=source.commit,
            release_digest=parsed_release.digest,
            configuration_digest=configuration.digest,
            runtime_bundle_digest=runtime_bundle.digest,
            native_scope_digest=native_scope.digest,
            settings_digest=settings_digest(settings),
            bound_settings_digest=settings_digest(replace(settings, product=product)),
            hub_key_id=key_id_for(hub_public),
            image_digests=tuple(sorted(digests.values())),
            destination=str(destination),
            mutation_performed=False,
            deployment_ready=False,
        )
        _write_json(destination / "preparation-receipt.json", receipt.model_dump(mode="json"))
        load_local_policy(destination / "local-policy.json")
        return receipt
    except BaseException:
        if destination.exists():
            for path in sorted(
                destination.rglob("*"),
                key=lambda item: len(item.parts),
                reverse=True,
            ):
                if path.is_file() or path.is_symlink():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            destination.rmdir()
        raise


def refresh_enrollment(
    *,
    prepared: Path,
    destination: Path,
    now: datetime,
) -> EnrollmentRefreshReceipt:
    """Refresh only enrollment freshness while preserving the prepared installation identity."""

    if now.tzinfo is None:
        raise ValueError("Enrollment refresh time must include a timezone.")
    prepared = prepared.absolute()
    destination = destination.absolute()
    if destination.parent != prepared or destination.exists() or destination.is_symlink():
        raise ValueError("Refreshed enrollment must be a new file in the prepared directory.")

    private_key = serialization.load_pem_private_key(
        read_private_bytes(prepared / "installation-private.pem", max_bytes=16 * 1024),
        password=None,
    )
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("Prepared installation key must be Ed25519.")
    signed = schemas.SignedEnrollment.model_validate_json(
        read_private_bytes(prepared / "signed-enrollment.json", max_bytes=256 * 1024)
    )
    request = schemas.enrollment_request(signed.signed_payload, signed.proof)
    if raw_public_key(private_key) != request.installation_key or not verify_key_proof(
        public_key=request.installation_key,
        payload=request.signed_payload,
        signature=request.proof,
    ):
        raise ValueError("Prepared enrollment proof does not match the installation key.")
    payload = schemas.EnrollmentPayload.model_validate_json(signed.signed_payload)
    template = payload.model_dump(
        mode="json",
        exclude={"installation_key", "requested_at"},
    )
    refreshed = schemas.sign_enrollment(template, private_key, now)
    document = schemas.SignedEnrollment.model_validate(
        {
            "signed_payload": base64.b64encode(refreshed.signed_payload).decode("ascii"),
            "proof": base64.b64encode(refreshed.proof).decode("ascii"),
        }
    )
    _write_json(destination, document.model_dump(mode="json"))
    return EnrollmentRefreshReceipt(
        schema_version="fdai.enrollment-refresh-receipt.v1",
        installation_id=refreshed.installation.installation_id,
        installation_key_id=refreshed.installation_key_id,
        requested_at=now,
        destination=str(destination),
        mutation_performed=True,
    )


def _component_images(
    path: Path,
    bundle: RuntimeBundle,
    entity_id: str,
) -> dict[str, str]:
    document = load_json_object(
        read_private_bytes(path.absolute(), max_bytes=64 * 1024),
        label="component images",
        strict=True,
    )
    expected = bundle.components(entity_id)
    if set(document) != expected:
        raise ValueError("Component image selection differs from the runtime bundle.")
    selected: dict[str, str] = {}
    for name, value in document.items():
        if not isinstance(value, str) or (match := _IMAGE.fullmatch(value)) is None:
            raise ValueError("Component image references must be immutable.")
        if not is_repository(match.group("repository")):
            raise ValueError("Component image repository is invalid.")
        selected[name] = value
    return selected


def _configuration_schema(release_id: str, bundle_digest: str) -> dict[str, object]:
    keys = {
        "runtime_bundle_digest": {
            "default": bundle_digest,
            "x-fdai-axis": "installation-path",
            "x-fdai-owner": "customer",
        }
    }
    return {
        "format": "fdai.release-configuration-schema.v1",
        "release_version": release_id,
        "schema_sha256": canonical_digest(keys),
        "keys": keys,
    }


def _major_range(release_id: str) -> str:
    major = int(release_id.split(".", 1)[0])
    return f">={major}.0.0 <{major + 1}.0.0"


def _write_key_pair(root: Path, name: str, key: Ed25519PrivateKey) -> None:
    write_private_bytes(
        root / f"{name}-private.pem",
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )
    _write_public_key(root / f"{name}-public.pem", key.public_key())


def _write_public_key(path: Path, key: Ed25519PublicKey) -> None:
    write_private_bytes(
        path,
        key.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ),
    )


def _write_json(path: Path, value: object) -> None:
    write_private_bytes(path, canonical_bytes(value))


__all__ = ["PreparationReceipt", "prepare_installation"]
