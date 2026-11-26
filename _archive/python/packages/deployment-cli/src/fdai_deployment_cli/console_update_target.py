"""Validate the secret-free target manifest for an existing Console update."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from fdai_deployment_cli.release_version import canonical_release_version
from fdai_deployment_cli.stencil_console import console_update_stencil_flags
from fdai_deployment_cli.target import compute_target_binding

_GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_API_SCOPE = re.compile(rf"api://{_GUID.pattern}/[A-Za-z0-9._-]+")
_HOSTNAME = re.compile(r"[a-z0-9-]+(?:[.][0-9]+)?[.]azurestaticapps[.]net")
_RESOURCE_ID = re.compile(
    r"/subscriptions/([^/]+)/resourceGroups/([^/]+)/providers/"
    r"Microsoft[.]Web/staticSites/([^/]+)",
    re.IGNORECASE,
)
_TARGET_FIELDS = frozenset(
    {
        "schema_version",
        "environment",
        "subscription_id",
        "tenant_id",
        "console_static_web_app_id",
        "console_hostname",
        "operator_api_base_url",
        "ingestion_api_base_url",
        "entra_console_spa_client_id",
        "entra_console_api_scope",
        "release_version",
        "stencil_feature_flags",
    }
)


@dataclass(frozen=True, slots=True)
class ConsoleUpdateTarget:
    """Secret-free existing Console binding supplied outside source control."""

    environment: str
    subscription_id: str
    tenant_id: str
    console_static_web_app_id: str
    console_hostname: str
    operator_api_base_url: str
    ingestion_api_base_url: str
    entra_console_spa_client_id: str
    entra_console_api_scope: str
    release_version: str
    stencil_feature_flags: dict[str, object]

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ConsoleUpdateTarget:
        """Decode a closed target manifest and reject unsafe endpoint bindings."""

        if (
            set(value) != _TARGET_FIELDS
            or value.get("schema_version") != "fdai.console-update-target.v2"
        ):
            raise ValueError("Console update target fields are invalid")
        text = {
            key: item
            for key, item in value.items()
            if key not in {"schema_version", "stencil_feature_flags"} and isinstance(item, str)
        }
        if len(text) != len(_TARGET_FIELDS) - 2:
            raise ValueError("Console update target values MUST be strings")
        target = cls(
            **text,
            stencil_feature_flags=console_update_stencil_flags(value.get("stencil_feature_flags")),
        )
        target.validate()
        return target

    def validate(self) -> None:
        """Validate the development-only target and its public, non-secret bindings."""

        if self.environment != "dev":
            raise ValueError("existing Console source updates are supported only in dev")
        for label, value in (
            ("subscription", self.subscription_id),
            ("tenant", self.tenant_id),
            ("Console SPA client", self.entra_console_spa_client_id),
        ):
            if _GUID.fullmatch(value) is None:
                raise ValueError(f"Console update {label} id is invalid")
        match = _RESOURCE_ID.fullmatch(self.console_static_web_app_id)
        if match is None or match.group(1).casefold() != self.subscription_id:
            raise ValueError("Console update Static Web App resource id is invalid")
        if _HOSTNAME.fullmatch(self.console_hostname) is None:
            raise ValueError("Console update hostname is invalid")
        for label, value in (
            ("Operator API", self.operator_api_base_url),
            ("ingestion API", self.ingestion_api_base_url),
        ):
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(f"Console update {label} URL is invalid")
        if _API_SCOPE.fullmatch(self.entra_console_api_scope) is None:
            raise ValueError("Console update API scope is invalid")
        canonical_release_version(
            self.release_version,
            context="Console update release_version",
        )
        console_update_stencil_flags(self.stencil_feature_flags)

    @property
    def target_binding(self) -> str:
        """Return the canonical tenant and subscription binding."""

        return compute_target_binding(
            tenant_id=self.tenant_id,
            subscription_id=self.subscription_id,
        )

    def to_mapping(self) -> dict[str, object]:
        """Return canonical target data for a private plan."""

        return {
            "schema_version": "fdai.console-update-target.v2",
            "environment": self.environment,
            "subscription_id": self.subscription_id,
            "tenant_id": self.tenant_id,
            "console_static_web_app_id": self.console_static_web_app_id,
            "console_hostname": self.console_hostname,
            "operator_api_base_url": self.operator_api_base_url,
            "ingestion_api_base_url": self.ingestion_api_base_url,
            "entra_console_spa_client_id": self.entra_console_spa_client_id,
            "entra_console_api_scope": self.entra_console_api_scope,
            "release_version": self.release_version,
            "stencil_feature_flags": self.stencil_feature_flags,
        }


__all__ = ["ConsoleUpdateTarget"]
