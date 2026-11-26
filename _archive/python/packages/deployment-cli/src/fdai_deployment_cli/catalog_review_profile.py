"""Private, content-addressed standalone catalog-review deployment profile."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.private_output import read_private_bytes
from fdai_deployment_cli.standalone_host_state import replace_or_verify_private_json

_SCHEMA = "fdai.catalog-review-deployment-profile.v1"
_STAGED_SCHEMA = "fdai.catalog-review-staged-profile.v1"
_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})$")
_BRANCH = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._/-]{0,254})$")
_MAX_PROFILE_BYTES = 64 * 1024
_MAX_PRIVATE_KEY_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class CatalogReviewDeploymentProfile:
    """Reviewed selection plus a private GitHub App key file reference."""

    selected: bool
    owner: str = ""
    repo: str = ""
    default_branch: str = ""
    app_client_id: str = ""
    app_installation_id: str = ""
    private_key_path: Path | None = None
    private_key_sha256: str = ""
    profile_digest: str = ""

    @classmethod
    def unselected(cls) -> CatalogReviewDeploymentProfile:
        material = {"schema_version": _SCHEMA, "selected": False}
        return cls(selected=False, profile_digest=canonical_digest(material))

    def staged_mapping(self) -> dict[str, object]:
        material = self._material(schema_version=_STAGED_SCHEMA)
        return {**material, "profile_digest": self.profile_digest}

    def private_key_text(self) -> str:
        if not self.selected or self.private_key_path is None:
            raise ValueError("selected catalog review profile has no private key reference")
        content = read_private_bytes(
            self.private_key_path,
            max_bytes=_MAX_PRIVATE_KEY_BYTES,
        )
        if hashlib.sha256(content).hexdigest() != self.private_key_sha256:
            raise ValueError("catalog review GitHub App private key changed after profile review")
        try:
            return content.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError("catalog review GitHub App private key MUST be ASCII PEM") from exc

    def _material(self, *, schema_version: str) -> dict[str, object]:
        if not self.selected:
            return {"schema_version": schema_version, "selected": False}
        return {
            "schema_version": schema_version,
            "selected": True,
            "owner": self.owner,
            "repo": self.repo,
            "default_branch": self.default_branch,
            "app_client_id": self.app_client_id,
            "app_installation_id": self.app_installation_id,
            "private_key_sha256": self.private_key_sha256,
        }


def load_catalog_review_profile(path: Path) -> CatalogReviewDeploymentProfile:
    """Load one operator-supplied private profile and its referenced private key."""

    value = _read_json(path, label="catalog review deployment profile")
    if value.get("schema_version") != _SCHEMA or not isinstance(value.get("selected"), bool):
        raise ValueError("catalog review deployment profile schema is invalid")
    if value["selected"] is False:
        if set(value) != {"schema_version", "selected"}:
            raise ValueError("unselected catalog review profile MUST contain no binding")
        return CatalogReviewDeploymentProfile.unselected()
    expected = {
        "schema_version",
        "selected",
        "owner",
        "repo",
        "default_branch",
        "app_client_id",
        "app_installation_id",
        "app_private_key_file",
    }
    if set(value) != expected:
        raise ValueError("selected catalog review deployment profile is incomplete")
    owner = _name(value, "owner")
    repo = _name(value, "repo")
    default_branch = value.get("default_branch")
    client_id = value.get("app_client_id")
    installation_id = value.get("app_installation_id")
    key_reference = value.get("app_private_key_file")
    if (
        not isinstance(default_branch, str)
        or _BRANCH.fullmatch(default_branch) is None
        or not isinstance(client_id, str)
        or not client_id.strip()
        or len(client_id) > 256
        or not isinstance(installation_id, str)
        or re.fullmatch(r"[1-9][0-9]*", installation_id) is None
        or not isinstance(key_reference, str)
        or not key_reference
    ):
        raise ValueError("catalog review GitHub App binding is invalid")
    key_path = Path(key_reference)
    if not key_path.is_absolute():
        key_path = path.parent / key_path
    key_content = read_private_bytes(key_path, max_bytes=_MAX_PRIVATE_KEY_BYTES)
    key_digest = hashlib.sha256(key_content).hexdigest()
    material = {
        "schema_version": _SCHEMA,
        "selected": True,
        "owner": owner,
        "repo": repo,
        "default_branch": default_branch,
        "app_client_id": client_id.strip(),
        "app_installation_id": installation_id,
        "private_key_sha256": key_digest,
    }
    return CatalogReviewDeploymentProfile(
        selected=True,
        owner=owner,
        repo=repo,
        default_branch=default_branch,
        app_client_id=client_id.strip(),
        app_installation_id=installation_id,
        private_key_path=key_path,
        private_key_sha256=key_digest,
        profile_digest=canonical_digest(material),
    )


def load_staged_catalog_review_profile(
    path: Path,
    *,
    private_key_path: Path | None,
) -> CatalogReviewDeploymentProfile:
    """Verify the remote staged profile and separately transferred key bytes."""

    value = _read_json(path, label="staged catalog review profile")
    supplied_digest = value.pop("profile_digest", None)
    if value.get("schema_version") != _STAGED_SCHEMA or not isinstance(value.get("selected"), bool):
        raise ValueError("staged catalog review profile schema is invalid")
    if value["selected"] is False:
        if set(value) != {"schema_version", "selected"} or private_key_path is not None:
            raise ValueError("unselected staged catalog review profile has unexpected binding")
        expected = CatalogReviewDeploymentProfile.unselected()
        if supplied_digest != expected.profile_digest:
            raise ValueError("staged catalog review profile digest differs")
        return expected
    expected_fields = {
        "schema_version",
        "selected",
        "owner",
        "repo",
        "default_branch",
        "app_client_id",
        "app_installation_id",
        "private_key_sha256",
    }
    if set(value) != expected_fields or private_key_path is None:
        raise ValueError("selected staged catalog review profile is incomplete")
    private_key_sha256 = str(value.get("private_key_sha256", ""))
    default_branch = value.get("default_branch")
    app_client_id = value.get("app_client_id")
    app_installation_id = value.get("app_installation_id")
    if (
        not isinstance(default_branch, str)
        or _BRANCH.fullmatch(default_branch) is None
        or not isinstance(app_client_id, str)
        or not app_client_id.strip()
        or len(app_client_id) > 256
        or not isinstance(app_installation_id, str)
        or re.fullmatch(r"[1-9][0-9]*", app_installation_id) is None
        or re.fullmatch(r"[0-9a-f]{64}", private_key_sha256) is None
    ):
        raise ValueError("staged catalog review GitHub App binding is invalid")
    content = read_private_bytes(private_key_path, max_bytes=_MAX_PRIVATE_KEY_BYTES)
    if hashlib.sha256(content).hexdigest() != private_key_sha256:
        raise ValueError("staged catalog review GitHub App private key digest differs")
    material = {
        "schema_version": _SCHEMA,
        "selected": True,
        "owner": _name(value, "owner"),
        "repo": _name(value, "repo"),
        "default_branch": default_branch,
        "app_client_id": app_client_id.strip(),
        "app_installation_id": app_installation_id,
        "private_key_sha256": private_key_sha256,
    }
    if canonical_digest(material) != supplied_digest:
        raise ValueError("staged catalog review profile digest differs")
    return CatalogReviewDeploymentProfile(
        selected=True,
        owner=str(material["owner"]),
        repo=str(material["repo"]),
        default_branch=str(material["default_branch"]),
        app_client_id=str(material["app_client_id"]),
        app_installation_id=str(material["app_installation_id"]),
        private_key_path=private_key_path,
        private_key_sha256=private_key_sha256,
        profile_digest=str(supplied_digest),
    )


def staged_catalog_review_profile_from_paths(
    profile_path: Path | None,
    private_key_path: Path | None,
) -> CatalogReviewDeploymentProfile:
    """Resolve optional staged paths into an explicit selected or skipped profile."""

    if profile_path is None:
        if private_key_path is not None:
            raise ValueError("catalog review private key requires its reviewed profile")
        return CatalogReviewDeploymentProfile.unselected()
    return load_staged_catalog_review_profile(
        profile_path,
        private_key_path=private_key_path,
    )


def catalog_review_terraform_values(
    profile: CatalogReviewDeploymentProfile,
) -> dict[str, object]:
    """Return private Terraform inputs without placing values in process arguments."""

    values: dict[str, object] = {"enable_catalog_review": profile.selected}
    if profile.selected:
        values.update(
            gitops_owner=profile.owner,
            gitops_repo=profile.repo,
            catalog_review_default_branch=profile.default_branch,
            github_app_client_id=profile.app_client_id,
            github_app_installation_id=profile.app_installation_id,
            github_app_private_key=profile.private_key_text(),
        )
    return values


def stage_catalog_review_profile(
    profile: CatalogReviewDeploymentProfile,
    *,
    tunnel: Any,
    prepared_root: Path,
    remote_root: str,
) -> tuple[str, ...]:
    """Copy private profile records and return value-free prepare arguments."""

    local_profile = prepared_root / "catalog-review-profile.json"
    remote_profile = f"{remote_root}/catalog-review-profile.json"
    replace_or_verify_private_json(local_profile, profile.staged_mapping())
    remote_key = f"{remote_root}/catalog-review-private-key.pem"
    try:
        tunnel.copy_to(local_profile, remote_profile, timeout=120)
        arguments: tuple[str, ...] = ("--catalog-review-profile", remote_profile)
        if not profile.selected:
            return arguments
        if profile.private_key_path is None:
            raise ValueError("selected catalog review profile has no private key reference")
        tunnel.copy_to(profile.private_key_path, remote_key, timeout=120)
        return (*arguments, "--catalog-review-private-key", remote_key)
    except BaseException:
        tunnel.ssh(
            ("rm", "-f", "--", remote_profile, remote_key),
            timeout=60,
        )
        raise


def _read_json(path: Path, *, label: str) -> dict[str, object]:
    content = read_private_bytes(path, max_bytes=_MAX_PROFILE_BYTES)
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} MUST be an object")
    return {str(key): item for key, item in value.items()}


def _name(value: dict[str, object], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or _NAME.fullmatch(item) is None:
        raise ValueError(f"catalog review GitOps {field} is invalid")
    return item


__all__ = [
    "CatalogReviewDeploymentProfile",
    "catalog_review_terraform_values",
    "load_catalog_review_profile",
    "load_staged_catalog_review_profile",
    "staged_catalog_review_profile_from_paths",
    "stage_catalog_review_profile",
]
