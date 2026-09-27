"""Resolve an AKS catalog-review Job from a protected GitOps binding."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

_GIT_REF_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})$")
_SECRET_ID = re.compile(
    r"^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/"
    r"Microsoft[.]KeyVault/vaults/[^/]+/secrets/([^/]+)$",
    re.IGNORECASE,
)
_SOURCE_REVISION = re.compile(r"^[0-9a-f]{40}$")

FROZEN_MANIFEST_PATH = (
    "services/core-control-plane/tests/scenarios/operational-learning/"
    "v2026.08-governed-learning.json"
)
FROZEN_SCENARIO_DIRECTORY = "services/core-control-plane/tests/scenarios/v2026.09"
REQUIRED_GITHUB_APP_PERMISSIONS = {
    "contents": "write",
    "issues": "write",
    "metadata": "read",
    "pull_requests": "write",
}


@dataclass(frozen=True, slots=True)
class AksCatalogReviewConfiguration:
    """Value-only and secret-reference inputs for one suspended Job template."""

    environment: dict[str, str]
    secret_environment: dict[str, str]


def aks_catalog_review_configuration(
    binding: object,
    *,
    selected: bool,
    source_revision: str,
) -> AksCatalogReviewConfiguration | None:
    """Validate one Terraform-owned private binding without resolving its secret."""

    if not selected:
        if binding is not None:
            raise ValueError("unselected catalog review has an unexpected GitOps binding")
        return None
    if binding is None:
        raise ValueError("selected catalog review private GitOps binding is unavailable")
    if _SOURCE_REVISION.fullmatch(source_revision) is None:
        raise ValueError("catalog review source revision MUST be an exact git SHA")
    value = _mapping(binding)
    if value.get("enabled") is not True:
        raise ValueError("catalog review GitOps binding is not enabled")
    owner = _required_name(value, "owner")
    repo = _required_name(value, "repo")
    auth_mode = value.get("auth_mode")
    default_branch = value.get("default_branch")
    permissions = value.get("permissions")
    if (
        auth_mode != "github_app"
        or not isinstance(default_branch, str)
        or not default_branch
        or permissions != REQUIRED_GITHUB_APP_PERMISSIONS
    ):
        raise ValueError("catalog review requires the exact GitHub App permission projection")
    environment = {
        "FDAI_CATALOG_REVIEW_ENABLED": "1",
        "FDAI_CATALOG_REVIEW_PROTECTED_BINDING": "1",
        "FDAI_CATALOG_REVIEW_SOURCE_REVISION": source_revision,
        "FDAI_CATALOG_REVIEW_EXPECTED_SCENARIO_SET_VERSION": "v2026.08",
        "FDAI_CATALOG_REVIEW_FROZEN_MANIFEST": FROZEN_MANIFEST_PATH,
        "FDAI_CATALOG_REVIEW_SCENARIO_DIR": FROZEN_SCENARIO_DIRECTORY,
        "FDAI_CATALOG_REVIEW_SCENARIO_SET_ID": "v2026.09",
        "FDAI_CATALOG_REVIEW_POLICY_VERSION": "operational-catalog-policy-v1",
        "FDAI_CATALOG_REVIEW_TIMEOUT_SECONDS": "240",
        "FDAI_EXECUTION_VENUE": "deployed",
        "FDAI_GITOPS_OWNER": owner,
        "FDAI_GITOPS_REPO": repo,
        "FDAI_GITOPS_DEFAULT_BRANCH": default_branch,
    }
    client_id = value.get("app_client_id")
    installation_id = value.get("app_installation_id")
    if (
        not isinstance(client_id, str)
        or not client_id.strip()
        or len(client_id) > 256
        or not isinstance(installation_id, str)
        or re.fullmatch(r"[1-9][0-9]*", installation_id) is None
    ):
        raise ValueError("catalog review GitHub App binding is incomplete")
    environment.update(
        {
            "FDAI_GITHUB_APP_CLIENT_ID": client_id.strip(),
            "FDAI_GITHUB_APP_INSTALLATION_ID": installation_id,
        }
    )
    secret_environment = {
        "FDAI_GITHUB_APP_PRIVATE_KEY": _secret_name(value.get("app_private_key_secret_id"))
    }
    return AksCatalogReviewConfiguration(
        environment=environment,
        secret_environment=secret_environment,
    )


def _required_name(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or item != item.strip() or _GIT_REF_NAME.fullmatch(item) is None:
        raise ValueError(f"catalog review GitOps {key} is invalid")
    return item


def _secret_name(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("catalog review private GitOps credential binding is unavailable")
    match = _SECRET_ID.fullmatch(value)
    if match is None or _GIT_REF_NAME.fullmatch(match.group(1)) is None:
        raise ValueError("catalog review private GitOps credential binding is unavailable")
    return match.group(1)


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError("catalog review GitOps binding MUST be an object")
    return value


__all__ = [
    "AksCatalogReviewConfiguration",
    "FROZEN_MANIFEST_PATH",
    "FROZEN_SCENARIO_DIRECTORY",
    "REQUIRED_GITHUB_APP_PERMISSIONS",
    "aks_catalog_review_configuration",
]
