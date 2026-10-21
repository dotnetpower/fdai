"""Read CSI reference metadata, never Kubernetes Secret data or mounted files."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol, TypedDict, Unpack

from fdai_deployment_cli.contracts import canonical_digest

from fdai_lifecycle_agent.workload import ENTITY_LABEL, Manifest, WorkloadError, is_dns_label

type ReferenceState = Literal[
    "unavailable", "unknown", "stale", "conflict", "reported-mounted", "reported-unmounted"
]
_OBJECT_NAME = re.compile(
    r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*\Z", re.ASCII
)


def is_reference_object_name(value: str) -> bool:
    """CSI status names use Kubernetes DNS subdomains (253), not namespace labels (63)."""
    return 0 < len(value) <= 253 and _OBJECT_NAME.fullmatch(value) is not None


class ReferenceStatusSource(Protocol):
    """Installation-bound read-only metadata seam; absence is not successful resolution."""

    def read_csi_object(self, kind: str, name: str) -> Manifest | None: ...


@dataclass(frozen=True, slots=True)
class ReferenceReadBudget:
    """Accept batch reads only before the deadline; do not interrupt or retry SDK requests."""

    source: ReferenceStatusSource
    deadline: float
    monotonic: Callable[[], float]

    def read_csi_object(self, kind: str, name: str) -> Manifest | None:
        if self.monotonic() >= self.deadline:
            raise WorkloadError("reference_read_deadline")
        result = self.source.read_csi_object(kind, name)
        if self.monotonic() >= self.deadline:
            raise WorkloadError("reference_read_deadline")
        return result


@dataclass(frozen=True, slots=True, kw_only=True)
class CSIReference:
    entity_id: str
    namespace: str
    pod_name: str
    pod_uid: str
    class_name: str
    status_name: str
    object_id: str
    object_version: str
    source_manager: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not 0 < len(value) <= 256
            for value in asdict(self).values()
        ):
            raise ValueError("CSI reference binding is invalid")
        if not is_dns_label(self.namespace) or not all(
            is_reference_object_name(name)
            for name in (self.pod_name, self.class_name, self.status_name)
        ):
            raise ValueError("CSI reference binding is invalid")


@dataclass(frozen=True, slots=True)
class ReferenceObservation:
    state: ReferenceState
    entity_id: str
    binding_digest: str
    source: str = "kubernetes/secrets-store.csi.x-k8s.io/v1/SecretProviderClassPodStatus"
    source_version: str | None = None
    pod_uid: str | None = None
    object_id: str | None = None
    object_version: str | None = None
    observed_at: str | None = None
    read_at: str | None = None

    def to_json(self) -> dict[str, object]:
        return asdict(self)


class _ObservationMetadata(TypedDict, total=False):
    source_version: str | None
    pod_uid: str | None
    object_id: str | None
    object_version: str | None
    observed_at: str | None


def observe_reference(
    reference: CSIReference,
    source: ReferenceStatusSource | None,
    *,
    now: datetime,
    maximum_age: timedelta = timedelta(minutes=5),
) -> ReferenceObservation:
    """Attribute CSI claims without upgrading ``mounted`` into operational verification.

    The API server's resource version identifies exact source bytes; a driver manager's
    update time bounds freshness of the report, not freshness or usability of secret values.
    Missing source bindings remain unavailable, including the default composition.
    """

    def result(
        state: ReferenceState, **metadata: Unpack[_ObservationMetadata]
    ) -> ReferenceObservation:
        return ReferenceObservation(
            state,
            reference.entity_id,
            canonical_digest(asdict(reference)),
            read_at=now.isoformat(),
            **metadata,
        )

    if source is None:
        return result("unavailable")
    if now.tzinfo is None or maximum_age <= timedelta(0):
        raise ValueError("CSI observation needs an aware clock and positive freshness bound")
    try:
        status = source.read_csi_object("SecretProviderClassPodStatus", reference.status_name)
        pod = source.read_csi_object("Pod", reference.pod_name)
        provider = source.read_csi_object("SecretProviderClass", reference.class_name)
    except WorkloadError:
        return result("unavailable")
    if status is None or pod is None or provider is None:
        return result("unavailable")
    for document, name in (
        (status, reference.status_name),
        (pod, reference.pod_name),
        (provider, reference.class_name),
    ):
        meta = _mapping(document.get("metadata"))
        if meta.get("namespace") != reference.namespace or meta.get("name") != name:
            return result("conflict")
    meta = _mapping(status.get("metadata"))
    pod_meta = _mapping(pod.get("metadata"))
    body = _mapping(status.get("status"))
    if (
        pod_meta.get("uid") != reference.pod_uid
        or _mapping(pod_meta.get("labels")).get(ENTITY_LABEL) != reference.entity_id
        or body.get("podName") != reference.pod_name
        or body.get("secretProviderClassName") != reference.class_name
        or _mapping(provider.get("spec")).get("provider") != "azure"
        or not any(
            isinstance(owner, Mapping)
            and owner.get("uid") == reference.pod_uid
            and owner.get("kind") == "Pod"
            for owner in _sequence(meta.get("ownerReferences"))
        )
        or not _pod_mounts(pod, reference.class_name)
    ):
        return result("conflict")
    version = meta.get("resourceVersion")
    if not isinstance(version, str) or not 0 < len(version) <= 128:
        return result("unknown")
    provenance: _ObservationMetadata = {
        "source_version": version,
        "pod_uid": reference.pod_uid,
        "object_id": reference.object_id,
        "object_version": reference.object_version,
    }
    matches = [
        item
        for item in _sequence(body.get("objects"))
        if isinstance(item, Mapping) and item.get("id") == reference.object_id
    ]
    if len(matches) != 1 or matches[0].get("version") != reference.object_version:
        return result("conflict", **provenance)
    times: list[datetime] = []
    for entry in _sequence(meta.get("managedFields")):
        if not isinstance(entry, Mapping) or entry.get("manager") != reference.source_manager:
            continue
        try:
            stamp = datetime.fromisoformat(str(entry.get("time")).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                return result("unknown", **provenance)
            times.append(stamp)
        except ValueError:
            return result("unknown", **provenance)
    if not times:
        return result("unknown", **provenance)
    updated = max(times)
    provenance["observed_at"] = updated.isoformat()
    if updated > now:
        return result("conflict", **provenance)
    if now - updated > maximum_age:
        return result("stale", **provenance)
    mounted = body.get("mounted")
    if type(mounted) is not bool:
        return result("unknown", **provenance)
    return result("reported-mounted" if mounted else "reported-unmounted", **provenance)


def _pod_mounts(pod: Manifest, class_name: str) -> bool:
    for volume in _sequence(_mapping(pod.get("spec")).get("volumes")):
        csi = _mapping(_mapping(volume).get("csi"))
        if csi.get("driver") == "secrets-store.csi.k8s.io" and (
            _mapping(csi.get("volumeAttributes")).get("secretProviderClass") == class_name
        ):
            return True
    return False


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> list[object]:
    return value if isinstance(value, list) else []
