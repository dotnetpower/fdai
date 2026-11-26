"""Run exact-source OI-12 measurement and persist one private immutable receipt."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

import httpx

from fdai.delivery.azure.operational_history_archive import (
    AzureBlobOperationalHistoryArtifactStore,
    AzureBlobOperationalHistoryConfig,
)
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.operational_instance_certification import (
    OperationalCertificationSnapshot,
    reduce_operational_instance_certification,
)
from fdai.delivery.operational_instance_certification_postgres import (
    OperationalCertificationGenerationPendingError,
    PostgresOperationalCertificationSource,
    PostgresOperationalCertificationSourceConfig,
)
from fdai.delivery.operational_instance_certification_records import receipt_record

_REQUEST_PATTERN = re.compile(r"certify-instance-[0-9a-f]{48}")
_REVISION_PATTERN = re.compile(r"[0-9a-f]{40}")
_GENERATION_CONVERGENCE_TIMEOUT_SECONDS = 120.0
_GENERATION_CONVERGENCE_POLL_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class ProtectedCertificationOptions:
    """Bind one protected OI-12 campaign to its exact source and workflow run."""

    request_id: str
    source_revision: str
    campaign_run_id: int
    window_seconds: int

    def __post_init__(self) -> None:
        if _REQUEST_PATTERN.fullmatch(self.request_id) is None:
            raise ValueError("protected certification request id is invalid")
        if _REVISION_PATTERN.fullmatch(self.source_revision) is None:
            raise ValueError("protected certification source revision is invalid")
        if self.campaign_run_id < 1:
            raise ValueError("protected certification campaign run id MUST be positive")
        if not 30 <= self.window_seconds <= 900:
            raise ValueError("protected certification window MUST be in [30, 900] seconds")


async def run_protected_certification(
    options: ProtectedCertificationOptions,
    environ: Mapping[str, str],
) -> dict[str, object]:
    """Measure all seven axes and persist one content-addressed private receipt."""

    dsn = environ.get("FDAI_DATABASE_URL", "").strip()
    container_url = environ.get("FDAI_OPERATIONAL_HISTORY_CONTAINER_URL", "").strip()
    if not dsn or not container_url:
        raise ValueError("protected certification requires database and archive bindings")
    source = PostgresOperationalCertificationSource(
        config=PostgresOperationalCertificationSourceConfig(dsn=dsn)
    )
    start = await _capture_generation_converged(source)
    await asyncio.sleep(options.window_seconds)
    end = await _capture_generation_converged(source)
    receipt = reduce_operational_instance_certification(
        start,
        end,
        recorded_at=end.measured_at,
    )
    if not receipt.complete:
        missing = ",".join(axis.value for axis in receipt.unavailable_axes)
        raise RuntimeError(f"protected certification axes are unavailable: {missing}")
    record = receipt_record(receipt)
    content = (
        json.dumps(
            record,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    artifact_digest = hashlib.sha256(content).hexdigest()
    storage_ref = (
        f"operational-history/oi12/{options.request_id}/"
        f"{receipt.digest.removeprefix('sha256:')}.json"
    )
    async with httpx.AsyncClient() as http_client:
        artifacts = AzureBlobOperationalHistoryArtifactStore(
            config=AzureBlobOperationalHistoryConfig(container_url=container_url),
            identity=ManagedIdentityWorkloadIdentity.from_env(
                http_client=http_client,
                client_id_env="FDAI_MI_CLIENT_ID",
            ),
            http_client=http_client,
        )
        await artifacts.put(storage_ref, content, digest=artifact_digest)
        if await artifacts.get(storage_ref) != content:
            raise RuntimeError("protected certification receipt readback did not match")
    return {
        "request_id": options.request_id,
        "source_revision": options.source_revision,
        "campaign_run_id": options.campaign_run_id,
        "receipt_digest": receipt.digest,
        "artifact_digest": f"sha256:{artifact_digest}",
        "storage_ref": storage_ref,
        "complete": True,
        "observation_authority": False,
        "mutation_authority": False,
        "execution_authority": False,
    }


async def _capture_generation_converged(
    source: PostgresOperationalCertificationSource,
) -> OperationalCertificationSnapshot:
    """Wait for the active inventory and ontology generations within a fixed deadline."""

    loop = asyncio.get_running_loop()
    deadline = loop.time() + _GENERATION_CONVERGENCE_TIMEOUT_SECONDS
    while True:
        try:
            return await source.capture()
        except OperationalCertificationGenerationPendingError:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise
            await asyncio.sleep(min(_GENERATION_CONVERGENCE_POLL_SECONDS, remaining))


__all__ = ["ProtectedCertificationOptions", "run_protected_certification"]
