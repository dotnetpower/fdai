"""Read independently managed knowledge policy with bounded no-follow file access."""

import os
import stat
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from fdai_service_contracts import DocumentAccessDeniedError, DocumentVersion
from fdai_service_contracts.cloud_knowledge import SourceRegistryRevision
from fdai_service_contracts.cloud_knowledge_admission import validate_admitted_binding
from fdai_service_contracts.cloud_knowledge_package import KnowledgeTrustPolicy


def policy_reader(
    environ: Mapping[str, str],
) -> Callable[[], tuple[SourceRegistryRevision, KnowledgeTrustPolicy]]:
    """Capture policy locations, not mutable policy or trust assertions supplied by a request."""
    registry_path = environ.get("FDAI_CLOUD_KNOWLEDGE_REGISTRY_PATH", "")
    trust_path = environ.get("FDAI_CLOUD_KNOWLEDGE_TRUST_PATH", "")

    def read() -> tuple[SourceRegistryRevision, KnowledgeTrustPolicy]:
        try:
            return (
                SourceRegistryRevision.model_validate_json(_read(registry_path)),
                KnowledgeTrustPolicy.model_validate_json(_read(trust_path)),
            )
        except (OSError, ValueError):
            raise ValueError(
                "independent cloud knowledge policy is unavailable or invalid"
            ) from None

    return read


def _read(path: str) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("knowledge policy MUST be a regular file")
        content = stream.read(1024 * 1024 + 1)
    if len(content) > 1024 * 1024:
        raise ValueError("knowledge policy exceeds its byte limit")
    return content


def read_guard(environ: Mapping[str, str]) -> Callable[[DocumentVersion], None]:
    read = policy_reader(environ)

    def check(version: DocumentVersion) -> None:
        if version.cloud_knowledge is None:
            return
        try:
            registry, trust = read()
            validate_admitted_binding(
                version.cloud_knowledge, registry=registry, trust=trust, now=datetime.now(tz=UTC)
            )
        except ValueError:
            raise DocumentAccessDeniedError(
                "cloud knowledge admission is no longer valid"
            ) from None

    return check
