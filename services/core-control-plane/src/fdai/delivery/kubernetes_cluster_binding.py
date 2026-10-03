"""Validate bounded Kubernetes cluster observation bindings."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

_MAX_BINDINGS = 32
_MAX_JSON_BYTES = 128 * 1024
_ALLOWED_KEYS = frozenset(
    {
        "api_server",
        "audience",
        "auth_mode",
        "ca_digest",
        "ca_path",
        "ca_pem",
        "cluster_ref",
        "token_path",
    }
)


@dataclass(frozen=True, slots=True)
class KubernetesClusterBinding:
    """Bind one exact cluster identity to one authenticated API source."""

    api_server: str
    cluster_ref: str
    auth_mode: str
    ca_path: Path | None = None
    ca_pem: str | None = None
    ca_digest: str | None = None
    token_path: Path | None = None
    audience: str | None = None

    def __post_init__(self) -> None:
        parsed = urlparse(self.api_server)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Kubernetes binding api_server MUST be a credential-free HTTPS origin")
        normalized_ref = self.cluster_ref.strip().casefold()
        if (
            len(self.cluster_ref) > 512
            or not normalized_ref.startswith("/subscriptions/")
            or "/providers/microsoft.containerservice/managedclusters/" not in normalized_ref
        ):
            raise ValueError("Kubernetes binding cluster_ref MUST be an AKS ARM id")
        if self.ca_path is not None and self.ca_pem is not None:
            raise ValueError("Kubernetes binding accepts only one CA material source")
        if self.ca_path is None and self.ca_pem is None:
            raise ValueError("Kubernetes binding requires exactly one CA binding")
        if self.ca_pem is not None and (
            not self.ca_pem.strip() or len(self.ca_pem) > 65_536 or not self.ca_pem.isascii()
        ):
            raise ValueError("Kubernetes binding ca_pem MUST be bounded non-empty text")
        if self.ca_digest is not None and (
            len(self.ca_digest) != 71
            or not self.ca_digest.startswith("sha256:")
            or any(character not in "0123456789abcdef" for character in self.ca_digest[7:])
        ):
            raise ValueError("Kubernetes binding ca_digest MUST be sha256:<64 lowercase hex>")
        if self.ca_pem is not None and self.ca_digest is not None:
            actual_digest = "sha256:" + hashlib.sha256(self.ca_pem.encode("ascii")).hexdigest()
            if self.ca_digest != actual_digest:
                raise ValueError("Kubernetes binding ca_digest MUST match ca_pem")
        if self.auth_mode not in {"service-account", "workload-identity"}:
            raise ValueError("Kubernetes binding auth_mode is invalid")
        if self.auth_mode == "service-account":
            if self.token_path is None or self.audience is not None:
                raise ValueError("service-account binding requires only token_path")
        elif self.audience is None or not self.audience.strip() or self.token_path is not None:
            raise ValueError("workload-identity binding requires only audience")

    @property
    def scope_digest(self) -> str:
        """Return the customer-safe identity used in source-state metadata."""

        digest = hashlib.sha256(self.cluster_ref.strip().casefold().encode("utf-8")).hexdigest()
        return f"sha256:{digest}"


def parse_kubernetes_cluster_bindings(value: str) -> tuple[KubernetesClusterBinding, ...]:
    """Parse one bounded JSON array without accepting credential values."""

    if not value.strip() or len(value.encode("utf-8")) > _MAX_JSON_BYTES:
        raise ValueError("FDAI_KUBERNETES_CLUSTER_BINDINGS_JSON MUST be bounded non-empty JSON")
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("FDAI_KUBERNETES_CLUSTER_BINDINGS_JSON is invalid JSON") from exc
    if (
        not isinstance(payload, Sequence)
        or isinstance(payload, (str, bytes))
        or not 1 <= len(payload) <= _MAX_BINDINGS
    ):
        raise ValueError("Kubernetes cluster bindings MUST contain between 1 and 32 items")
    bindings = tuple(_binding(item) for item in payload)
    cluster_refs = {item.cluster_ref.strip().casefold() for item in bindings}
    api_servers = {item.api_server.rstrip("/").casefold() for item in bindings}
    if len(cluster_refs) != len(bindings):
        raise ValueError("Kubernetes cluster binding cluster_ref values MUST be unique")
    if len(api_servers) != len(bindings):
        raise ValueError("Kubernetes cluster binding api_server values MUST be unique")
    return bindings


def _binding(value: object) -> KubernetesClusterBinding:
    if not isinstance(value, Mapping) or set(value) - _ALLOWED_KEYS:
        raise ValueError("Kubernetes cluster binding MUST contain only supported fields")

    def text(key: str, *, required: bool = False) -> str | None:
        raw = value.get(key)
        if raw is None and not required:
            return None
        if not isinstance(raw, str) or not raw.strip() or len(raw) > 65_536:
            raise ValueError(f"Kubernetes cluster binding {key} MUST be bounded non-empty text")
        return raw.strip()

    ca_path = text("ca_path")
    ca_pem = text("ca_pem")
    ca_digest = text("ca_digest")
    token_path = text("token_path")
    return KubernetesClusterBinding(
        api_server=text("api_server", required=True) or "",
        cluster_ref=text("cluster_ref", required=True) or "",
        auth_mode=text("auth_mode", required=True) or "",
        ca_path=Path(ca_path) if ca_path is not None else None,
        ca_pem=ca_pem,
        ca_digest=ca_digest,
        token_path=Path(token_path) if token_path is not None else None,
        audience=text("audience"),
    )


__all__ = ["KubernetesClusterBinding", "parse_kubernetes_cluster_bindings"]
