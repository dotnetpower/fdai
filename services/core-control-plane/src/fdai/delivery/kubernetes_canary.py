"""Read-only AKS scheduler witnesses, independent of publisher and consumer receipts."""

from __future__ import annotations

import json
import re
import ssl
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from croniter import croniter
from fdai_service_contracts.compatibility import canonical_digest

from fdai.delivery.self_health_canary import _timestamp
from fdai.shared.providers.self_health import SelfHealthExporterUnavailableError

_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?")
_MAX_JOBS = 16
_MAX_BYTES = 262_144
_SERVICE_ACCOUNT = Path("/var/run/secrets/kubernetes.io/serviceaccount")
_METADATA_ACCEPT = "application/json;as=PartialObjectMetadataList;g=meta.k8s.io;v=v1"


@dataclass(frozen=True, slots=True)
class ScheduledCanaryWitness:
    slot: str
    scheduled_at: datetime
    valid_until: datetime
    binding_digest: str


def _in_cluster_client() -> httpx.AsyncClient:
    with (_SERVICE_ACCOUNT / "token").open("rb") as stream:
        encoded = stream.read(16_385)
    if not 1 <= len(encoded) <= 16_384:
        raise ValueError("canary observer service-account credential is out of bounds")
    token = encoded.decode("ascii").strip()
    if re.fullmatch(r"[A-Za-z0-9_.-]+", token) is None:
        raise ValueError("canary observer service-account credential is malformed")
    return httpx.AsyncClient(
        base_url="https://kubernetes.default.svc",
        headers={"Authorization": f"Bearer {token}", "Accept-Encoding": "identity"},
        verify=ssl.create_default_context(cafile=str(_SERVICE_ACCOUNT / "ca.crt")),
        timeout=0.4,
        trust_env=False,
        follow_redirects=False,
    )


@dataclass(frozen=True, slots=True)
class AksScheduledCanaryObserver:
    namespace: str
    cronjob: str
    client_factory: Callable[[], httpx.AsyncClient] = field(
        default=_in_cluster_client, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if (
            not 1 <= len(self.namespace) <= 63
            or not 1 <= len(self.cronjob) <= 52
            or _DNS_LABEL.fullmatch(self.namespace) is None
            or _DNS_LABEL.fullmatch(self.cronjob) is None
        ):
            raise ValueError("canary observer namespace and CronJob must be bounded DNS labels")

    async def observe(self, *, now: datetime) -> ScheduledCanaryWitness:
        if now.utcoffset() is None:
            raise ValueError("scheduler observation requires an aware timestamp")
        base = f"/apis/batch/v1/namespaces/{self.namespace}"
        try:
            async with self.client_factory() as client:
                cron = await _get_json(client, f"{base}/cronjobs/{self.cronjob}")
                jobs = await _get_json(
                    client,
                    f"{base}/jobs",
                    accept=_METADATA_ACCEPT,
                    params={
                        "labelSelector": f"app.kubernetes.io/name={self.cronjob}",
                        "limit": str(_MAX_JOBS + 1),
                    },
                )
                confirmation = await _get_json(client, f"{base}/cronjobs/{self.cronjob}")
            first = self._witness(cron, jobs, now=now.astimezone(UTC))
            last = self._witness(confirmation, jobs, now=now.astimezone(UTC))
            if first != last:
                raise SelfHealthExporterUnavailableError(reason="source_incomplete")
            return last
        except (httpx.HTTPError, OSError) as exc:
            raise SelfHealthExporterUnavailableError(reason="source_unreachable") from exc
        except (KeyError, TypeError, ValueError, OverflowError, RecursionError) as exc:
            raise SelfHealthExporterUnavailableError(reason="source_malformed") from exc

    def _witness(
        self, cron: Mapping[str, Any], jobs: Mapping[str, Any], *, now: datetime
    ) -> ScheduledCanaryWitness:
        if cron.get("apiVersion") != "batch/v1" or cron.get("kind") != "CronJob":
            raise ValueError("canary scheduler object has the wrong kind")
        metadata = _object(cron["metadata"])
        spec = _object(cron["spec"])
        if metadata["name"] != self.cronjob or metadata["namespace"] != self.namespace:
            raise ValueError("canary scheduler scope does not match")
        uid = _uuid(metadata["uid"])
        generation = metadata["generation"]
        if type(generation) is not int or generation < 1:
            raise ValueError("canary scheduler generation is malformed")
        if spec.get("suspend", False) is not False:
            raise SelfHealthExporterUnavailableError(reason="source_incomplete")
        if spec.get("timeZone") not in {"UTC", "Etc/UTC"}:
            raise SelfHealthExporterUnavailableError(reason="source_incomplete")
        schedule = spec["schedule"]
        if (
            not isinstance(schedule, str)
            or not 1 <= len(schedule) <= 256
            or len(schedule.split()) != 5
            or not croniter.is_valid(schedule, strict=True)
        ):
            raise ValueError("canary schedule is not a bounded five-field cron expression")
        expected = croniter(
            schedule, now + timedelta(microseconds=1), max_years_between_matches=8
        ).get_prev(datetime)
        valid_until = croniter(schedule, expected, max_years_between_matches=8).get_next(datetime)
        created_at = _timestamp(metadata["creationTimestamp"])
        if created_at > now:
            raise SelfHealthExporterUnavailableError(reason="source_from_future")
        if expected < created_at:
            raise SelfHealthExporterUnavailableError(reason="source_missing")
        if jobs.get("kind") != "PartialObjectMetadataList":
            raise ValueError("canary Job observation requires metadata-only content negotiation")
        listing = _object(jobs["metadata"])
        continuation = listing.get("continue", "")
        remaining = listing.get("remainingItemCount", 0)
        if not isinstance(continuation, str) or type(remaining) is not int or remaining < 0:
            raise ValueError("canary metadata pagination is malformed")
        if continuation or remaining:
            raise SelfHealthExporterUnavailableError(reason="source_incomplete")
        items = jobs["items"]
        if not isinstance(items, list) or len(items) > _MAX_JOBS:
            raise SelfHealthExporterUnavailableError(reason="source_incomplete")
        matches: list[str] = []
        for item in items:
            job = _object(_object(item)["metadata"])
            owners = job.get("ownerReferences")
            if not isinstance(owners, list) or len(owners) > 4:
                raise ValueError("canary Job owner reference is malformed")
            current_owners = [
                _object(owner)
                for owner in owners
                if _object(owner).get("controller") is True
                and _object(owner).get("kind") == "CronJob"
                and _object(owner).get("uid") == uid
            ]
            if not current_owners:
                continue
            if (
                len(current_owners) != 1
                or current_owners[0].get("apiVersion") != "batch/v1"
                or current_owners[0].get("name") != self.cronjob
                or job["namespace"] != self.namespace
                or _object(job["labels"]).get("app.kubernetes.io/name") != self.cronjob
            ):
                raise ValueError("canary Job controller scope conflicts")
            scheduled_at = _timestamp(
                _object(job["annotations"])["batch.kubernetes.io/cronjob-scheduled-timestamp"]
            )
            if scheduled_at > now:
                raise SelfHealthExporterUnavailableError(reason="source_from_future")
            if scheduled_at == expected:
                matches.append(_uuid(job["uid"]))
        if not matches:
            raise SelfHealthExporterUnavailableError(reason="source_missing")
        if len(matches) != 1:
            raise SelfHealthExporterUnavailableError(reason="source_incomplete")
        slot = f"aks-job:{matches[0]}"
        return ScheduledCanaryWitness(
            slot=slot,
            scheduled_at=expected,
            valid_until=valid_until,
            binding_digest=canonical_digest(
                {
                    "namespace": self.namespace,
                    "cronjob": self.cronjob,
                    "uid": uid,
                    "generation": generation,
                    "schedule": schedule,
                    "time_zone": spec["timeZone"],
                    "scheduled_at": expected.isoformat(),
                    "slot": slot,
                }
            ),
        )


async def _get_json(
    client: httpx.AsyncClient,
    path: str,
    *,
    accept: str = "application/json",
    params: Mapping[str, str] | None = None,
) -> Mapping[str, Any]:
    async with client.stream(
        "GET",
        path,
        params=params,
        headers={"Accept": accept, "Accept-Encoding": "identity"},
        follow_redirects=False,
    ) as response:
        response.raise_for_status()
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            raise ValueError("canary metadata response encoding is unsupported")
        data = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=8192):
            if len(data) + len(chunk) > _MAX_BYTES:
                raise SelfHealthExporterUnavailableError(reason="source_incomplete")
            data.extend(chunk)
        return _object(json.loads(data))


def _object(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("canary metadata is not an object")
    return value


def _uuid(value: object) -> str:
    if not isinstance(value, str) or len(value) != 36:
        raise ValueError("canary native identity is malformed")
    result = UUID(value)
    if str(result) != value or result.int == 0:
        raise ValueError("canary native identity is not canonical")
    return value
