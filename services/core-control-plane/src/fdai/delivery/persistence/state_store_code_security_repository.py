"""Registered code-security repositories over ``StateStore``.

A registration names one repository that FDAI may scan when an operator asks from the Console.
It holds the display alias, the provider (``github``), the ``owner/repository`` location, the
default ref (``HEAD`` follows the repository's default branch), the exposure used for priority,
and whether it is enabled. It never holds a
credential: the scan worker reads repository access from the deployment's GitHub App or token
environment, scoped to that one repository with read-only contents permission.

Registering a repository grants permission to fetch and scan it, nothing else. It grants no
approval, execution, or write access to the repository. Every create and enable or disable
change appends a Heimdall-attributed audit entry in the same transaction.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai.rule_catalog.code_security import Exposure
from fdai.shared.providers.state_store import StateStore

CODE_SECURITY_REPOSITORY_STATE_PREFIX = "runtime:code-security-repository:"
REPOSITORY_KIND = "code-security-repository"
PROVIDERS = ("github",)
_ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_GITHUB_LOCATION = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_PRINCIPAL = re.compile(r"^[A-Za-z0-9@._:/+-]{1,128}$")
_MAX_REPOSITORIES = 200


class CodeSecurityRepositoryError(ValueError):
    """A registration is malformed, conflicts with another, or does not exist."""


class CodeSecurityRepositoryNotFoundError(CodeSecurityRepositoryError):
    """The alias has no registration."""


@dataclass(frozen=True, slots=True)
class CodeSecurityRepository:
    repository_alias: str
    provider: str
    location: str
    default_ref: str
    exposure: str
    enabled: bool
    registered_at: str
    registered_by: str
    revision: int

    def as_record(self) -> dict[str, object]:
        return {
            "kind": REPOSITORY_KIND,
            "schema_version": "1.0.0",
            "repository_alias": self.repository_alias,
            "provider": self.provider,
            "location": self.location,
            "default_ref": self.default_ref,
            "exposure": self.exposure,
            "enabled": self.enabled,
            "registered_at": self.registered_at,
            "registered_by": self.registered_by,
            "revision": self.revision,
        }


def repository_state_key(alias: str) -> str:
    return f"{CODE_SECURITY_REPOSITORY_STATE_PREFIX}{alias}"


def validate_ref(ref: str) -> str:
    if _REF.fullmatch(ref) is None or ".." in ref:
        raise CodeSecurityRepositoryError("ref must be a branch, tag, or full commit id")
    return ref


def parse_repository(record: Mapping[str, object]) -> CodeSecurityRepository:
    """Return a validated registration or raise ``CodeSecurityRepositoryError``."""
    alias, provider, location = (
        record.get("repository_alias"),
        record.get("provider"),
        record.get("location"),
    )
    default_ref, exposure, enabled = (
        record.get("default_ref"),
        record.get("exposure"),
        record.get("enabled"),
    )
    registered_at, registered_by, revision = (
        record.get("registered_at"),
        record.get("registered_by"),
        record.get("revision"),
    )
    if record.get("kind") != REPOSITORY_KIND:
        raise CodeSecurityRepositoryError("record is not a code-security repository")
    if not isinstance(alias, str) or _ALIAS.fullmatch(alias) is None:
        raise CodeSecurityRepositoryError("repository_alias is invalid")
    if provider not in PROVIDERS:
        raise CodeSecurityRepositoryError("provider is not supported")
    if not isinstance(location, str) or _GITHUB_LOCATION.fullmatch(location) is None:
        raise CodeSecurityRepositoryError("location must be owner/repository")
    if not isinstance(default_ref, str):
        raise CodeSecurityRepositoryError("default_ref is invalid")
    validate_ref(default_ref)
    if exposure not in {item.value for item in Exposure}:
        raise CodeSecurityRepositoryError("exposure is invalid")
    if not isinstance(enabled, bool):
        raise CodeSecurityRepositoryError("enabled must be a boolean")
    if not isinstance(registered_at, str):
        raise CodeSecurityRepositoryError("registered_at is invalid")
    datetime.fromisoformat(registered_at)
    if not isinstance(registered_by, str) or _PRINCIPAL.fullmatch(registered_by) is None:
        raise CodeSecurityRepositoryError("registered_by is invalid")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise CodeSecurityRepositoryError("revision is invalid")
    return CodeSecurityRepository(
        repository_alias=alias,
        provider=str(provider),
        location=location,
        default_ref=default_ref,
        exposure=str(exposure),
        enabled=enabled,
        registered_at=registered_at,
        registered_by=registered_by,
        revision=revision,
    )


def _audit(repository: CodeSecurityRepository, change: str) -> dict[str, object]:
    return {
        "kind": "code_security_repository_changed",
        "producer_principal": "Heimdall",
        "change": change,
        "repository_alias": repository.repository_alias,
        "provider": repository.provider,
        "enabled": repository.enabled,
        "registration_revision": repository.revision,
        "actor": repository.registered_by,
        "execution_authority": False,
    }


async def register_repository(
    store: StateStore,
    *,
    alias: str,
    location: str,
    default_ref: str = "HEAD",
    exposure: Exposure = Exposure.UNKNOWN,
    registered_by: str,
    provider: str = "github",
    now: datetime | None = None,
) -> tuple[CodeSecurityRepository, bool]:
    """Register a repository once; return it and whether a new registration was created.

    Re-registering the same alias with the same location is a no-op. A different location for an
    existing alias is refused, so an alias can't be silently repointed at another repository.
    """
    candidate = parse_repository(
        {
            "kind": REPOSITORY_KIND,
            "repository_alias": alias,
            "provider": provider,
            "location": location,
            "default_ref": default_ref,
            "exposure": exposure.value,
            "enabled": True,
            "registered_at": (now or datetime.now(UTC)).isoformat(),
            "registered_by": registered_by,
            "revision": 1,
        }
    )
    key = repository_state_key(alias)
    if await store.write_state_with_audit_if_absent(
        key, candidate.as_record(), _audit(candidate, "registered")
    ):
        return candidate, True
    existing = await read_repository(store, alias)
    if existing is None or existing.location != location or existing.provider != provider:
        raise CodeSecurityRepositoryError(
            f"repository alias {alias} is already registered for another location"
        )
    return existing, False


async def read_repository(store: StateStore, alias: str) -> CodeSecurityRepository | None:
    if _ALIAS.fullmatch(alias) is None:
        raise CodeSecurityRepositoryError("repository_alias is invalid")
    record = await store.read_state(repository_state_key(alias))
    return None if record is None else parse_repository(record)


async def list_repositories(store: StateStore) -> tuple[CodeSecurityRepository, ...]:
    records = await store.read_states(
        CODE_SECURITY_REPOSITORY_STATE_PREFIX, limit=_MAX_REPOSITORIES
    )
    return tuple(
        sorted(
            (parse_repository(record) for record in records),
            key=lambda item: item.repository_alias,
        )
    )


async def set_repository_enabled(
    store: StateStore, alias: str, *, enabled: bool, actor: str
) -> CodeSecurityRepository:
    """Enable or disable scanning for one registration with compare-and-set plus audit."""
    if _PRINCIPAL.fullmatch(actor) is None:
        raise CodeSecurityRepositoryError("actor is invalid")
    for _attempt in range(4):
        existing = await read_repository(store, alias)
        if existing is None:
            raise CodeSecurityRepositoryNotFoundError(f"repository alias {alias} is not registered")
        if existing.enabled is enabled:
            return existing
        updated = CodeSecurityRepository(
            **{
                **{
                    field: getattr(existing, field)
                    for field in CodeSecurityRepository.__dataclass_fields__
                },
                "enabled": enabled,
                "revision": existing.revision + 1,
            }
        )
        audit = {**_audit(updated, "enabled" if enabled else "disabled"), "actor": actor}
        if await store.compare_and_set_state_with_audit(
            repository_state_key(alias),
            updated.as_record(),
            expected_revision=existing.revision,
            audit_entry=audit,
        ):
            return updated
    raise CodeSecurityRepositoryError("repository registration changed concurrently; retry")


def clone_url(repository: CodeSecurityRepository, base_url: str = "https://github.com") -> str:
    """Return the credential-free HTTPS clone URL for a registration."""
    base = base_url.rstrip("/")
    if not base.startswith("https://") or "@" in base:
        raise CodeSecurityRepositoryError("GitHub base URL must be credential-free HTTPS")
    return f"{base}/{repository.location}.git"


__all__ = [
    "CODE_SECURITY_REPOSITORY_STATE_PREFIX",
    "PROVIDERS",
    "REPOSITORY_KIND",
    "CodeSecurityRepository",
    "CodeSecurityRepositoryError",
    "CodeSecurityRepositoryNotFoundError",
    "clone_url",
    "list_repositories",
    "parse_repository",
    "read_repository",
    "register_repository",
    "repository_state_key",
    "set_repository_enabled",
    "validate_ref",
]
