"""Disabled-first atomic lifecycle for image-reviewed vertical packages."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from types import MappingProxyType
from typing import Any

import yaml

from fdai.core.capability_catalog import ExtensionState, ExtensionTrustVerifier
from fdai.core.vertical_packages.models import (
    InstalledVerticalPackage,
    VerticalAssetKind,
    VerticalPackageActivationMetadata,
    VerticalPackageAsset,
    VerticalPackageAvailability,
    VerticalPackageBundle,
    VerticalPackageLifecycleError,
    VerticalPackageRelease,
    VerticalPackageRuntime,
    VerticalPackageValidationError,
)
from fdai.shared.contracts.models import Mode

_FORBIDDEN_AUTHORITY_FIELDS = {
    "approval_authority",
    "can_approve",
    "can_execute",
    "can_promote",
    "execution_authority",
    "grants_authority",
    "mutation_authority",
    "promotion_authority",
}


class VerticalPackageManager:
    """Immutable manager that publishes only fully rebuilt package runtimes."""

    __slots__ = (
        "_base_runtime",
        "_host_reference_ids",
        "_host_version",
        "_installed",
        "_ontology_release_digest",
        "_provider_bindings",
    )

    def __init__(
        self,
        *,
        host_version: str,
        ontology_release_digest: str,
        provider_bindings: Iterable[str] = (),
        host_reference_ids: Iterable[str] = (),
        base_runtime: VerticalPackageRuntime | None = None,
        installed: Mapping[str, InstalledVerticalPackage] | None = None,
    ) -> None:
        _version_tuple(host_version)
        self._host_version = host_version
        self._ontology_release_digest = ontology_release_digest
        self._provider_bindings = frozenset(provider_bindings)
        self._host_reference_ids = frozenset(host_reference_ids)
        self._base_runtime = base_runtime or VerticalPackageRuntime()
        self._installed = MappingProxyType(dict(installed or {}))

    def install(
        self,
        bundle: VerticalPackageBundle,
        *,
        archive: bytes,
        image_digest: str,
        verifier: ExtensionTrustVerifier,
    ) -> VerticalPackageManager:
        """Verify and install one package disabled without changing this manager."""

        extension = bundle.manifest.extension
        if extension.extension_id in self._installed:
            raise VerticalPackageLifecycleError(
                f"vertical package {extension.extension_id!r} is already installed"
            )
        if (
            any(
                item.bundle.manifest.vertical_id == bundle.manifest.vertical_id
                for item in self._installed.values()
            )
            or bundle.manifest.vertical_id in self._base_runtime.packages
        ):
            raise VerticalPackageLifecycleError(
                f"vertical id {bundle.manifest.vertical_id!r} is already installed"
            )
        self._verify_candidate(bundle, archive=archive, verifier=verifier)
        _validate_install_collisions(
            bundle,
            base_runtime=self._base_runtime,
            installed=self._installed,
        )
        availability = _derive_availability(
            bundle,
            host_version=self._host_version,
            ontology_release_digest=self._ontology_release_digest,
            provider_bindings=self._provider_bindings,
        )
        installed = dict(self._installed)
        installed[extension.extension_id] = InstalledVerticalPackage(
            bundle=bundle,
            availability=availability,
            image_digest=image_digest,
        )
        return self._copy(installed)

    def upgrade(
        self,
        extension_id: str,
        bundle: VerticalPackageBundle,
        *,
        archive: bytes,
        image_digest: str,
        verifier: ExtensionTrustVerifier,
        expected_current_version: str,
    ) -> VerticalPackageManager:
        """Atomically replace a release and retain exactly its N-1 rollback state."""

        current = _require_package(self._installed, extension_id)
        current_manifest = current.bundle.manifest
        candidate_manifest = bundle.manifest
        if current_manifest.extension.version != expected_current_version:
            raise VerticalPackageLifecycleError("vertical package upgrade version conflict")
        if (
            candidate_manifest.extension.extension_id != extension_id
            or candidate_manifest.vertical_id != current_manifest.vertical_id
        ):
            raise VerticalPackageLifecycleError(
                "vertical package upgrade MUST preserve package and vertical identity"
            )
        if not _is_n_minus_one(
            current_manifest.extension.version,
            candidate_manifest.extension.version,
        ):
            raise VerticalPackageLifecycleError(
                "vertical package upgrade MUST advance exactly one patch release"
            )
        self._verify_candidate(bundle, archive=archive, verifier=verifier)
        other_installed = {
            package_id: installed
            for package_id, installed in self._installed.items()
            if package_id != extension_id
        }
        _validate_install_collisions(
            bundle,
            base_runtime=self._base_runtime,
            installed=other_installed,
        )
        availability = _derive_availability(
            bundle,
            host_version=self._host_version,
            ontology_release_digest=self._ontology_release_digest,
            provider_bindings=self._provider_bindings,
        )
        if current.state is ExtensionState.ENABLED and not availability.available:
            reasons = ", ".join(availability.reasons)
            raise VerticalPackageLifecycleError(
                f"enabled vertical package upgrade is unavailable: {reasons}"
            )
        installed = dict(self._installed)
        installed[extension_id] = InstalledVerticalPackage(
            bundle=bundle,
            availability=availability,
            image_digest=image_digest,
            state=current.state,
            previous_release=VerticalPackageRelease(
                bundle=current.bundle,
                availability=current.availability,
                image_digest=current.image_digest,
            ),
        )
        candidate = self._copy(installed)
        candidate.runtime()
        return candidate

    def rollback(
        self,
        extension_id: str,
        *,
        expected_current_version: str,
    ) -> VerticalPackageManager:
        """Atomically restore N-1 registrations without replaying runtime effects."""

        installed = dict(self._installed)
        current = _require_package(installed, extension_id)
        if current.bundle.manifest.extension.version != expected_current_version:
            raise VerticalPackageLifecycleError("vertical package rollback version conflict")
        previous = current.previous_release
        if previous is None:
            raise VerticalPackageLifecycleError(
                f"vertical package {extension_id!r} has no N-1 release"
            )
        installed[extension_id] = InstalledVerticalPackage(
            bundle=previous.bundle,
            availability=previous.availability,
            image_digest=previous.image_digest,
            state=current.state,
        )
        candidate = self._copy(installed)
        candidate.runtime()
        return candidate

    def enable(self, extension_id: str) -> VerticalPackageManager:
        """Atomically enable an available package by rebuilding from the base."""

        installed = dict(self._installed)
        current = _require_package(installed, extension_id)
        if current.state is ExtensionState.ENABLED:
            return self
        if not current.availability.available:
            reasons = ", ".join(current.availability.reasons)
            raise VerticalPackageLifecycleError(
                f"vertical package {extension_id!r} is unavailable: {reasons}"
            )
        installed[extension_id] = replace(current, state=ExtensionState.ENABLED)
        candidate = self._copy(installed)
        candidate.runtime()
        return candidate

    def disable(self, extension_id: str) -> VerticalPackageManager:
        """Atomically remove one package's registrations from the active runtime."""

        installed = dict(self._installed)
        current = _require_package(installed, extension_id)
        if current.state is ExtensionState.DISABLED:
            return self
        installed[extension_id] = replace(current, state=ExtensionState.DISABLED)
        candidate = self._copy(installed)
        candidate.runtime()
        return candidate

    def runtime(self) -> VerticalPackageRuntime:
        """Rebuild active packages and assets from the immutable base runtime."""

        packages = dict(self._base_runtime.packages)
        assets = dict(self._base_runtime.assets)
        asset_digests = {asset.declaration.sha256 for asset in assets.values()}
        for extension_id in sorted(self._installed):
            installed = self._installed[extension_id]
            if installed.state is not ExtensionState.ENABLED:
                continue
            bundle = installed.bundle
            vertical_id = bundle.manifest.vertical_id
            if vertical_id in packages:
                raise VerticalPackageLifecycleError(f"duplicate active vertical id {vertical_id!r}")
            for asset in bundle.assets:
                declaration = asset.declaration
                if declaration.asset_id in assets:
                    raise VerticalPackageLifecycleError(
                        f"duplicate active asset id {declaration.asset_id!r}"
                    )
                if declaration.sha256 in asset_digests:
                    raise VerticalPackageLifecycleError(
                        f"duplicate active asset digest {declaration.sha256!r}"
                    )
                assets[declaration.asset_id] = asset
                asset_digests.add(declaration.sha256)
            packages[vertical_id] = bundle
        return VerticalPackageRuntime(packages=packages, assets=assets)

    def availability(self, extension_id: str) -> VerticalPackageAvailability:
        """Return installed availability or a stable absent-package diagnostic."""

        installed = self._installed.get(extension_id)
        if installed is None:
            return VerticalPackageAvailability(available=False, reasons=("package_absent",))
        return installed.availability

    def activation_metadata(self, extension_id: str) -> VerticalPackageActivationMetadata:
        """Return manager-derived availability, enablement, and artifact attribution."""

        installed = _require_package(self._installed, extension_id)
        manifest = installed.bundle.manifest
        return VerticalPackageActivationMetadata(
            vertical_id=manifest.vertical_id,
            package_id=manifest.extension.extension_id,
            available=installed.availability.available,
            enabled=installed.state is ExtensionState.ENABLED,
            availability_reasons=installed.availability.reasons,
            package_version=manifest.extension.version,
            image_digest=installed.image_digest,
            asset_manifest_digest=f"sha256:{manifest.asset_manifest_sha256}",
            semantic_profile_digest=manifest.semantic_profile_sha256,
            ontology_release_digest=self._ontology_release_digest,
        )

    def list(self) -> tuple[tuple[str, ExtensionState, VerticalPackageAvailability], ...]:
        """Return installed package state and availability in stable order."""

        return tuple(
            (extension_id, installed.state, installed.availability)
            for extension_id, installed in sorted(self._installed.items())
        )

    def _copy(
        self,
        installed: Mapping[str, InstalledVerticalPackage],
    ) -> VerticalPackageManager:
        return VerticalPackageManager(
            host_version=self._host_version,
            ontology_release_digest=self._ontology_release_digest,
            provider_bindings=self._provider_bindings,
            host_reference_ids=self._host_reference_ids,
            base_runtime=self._base_runtime,
            installed=installed,
        )

    def _verify_candidate(
        self,
        bundle: VerticalPackageBundle,
        *,
        archive: bytes,
        verifier: ExtensionTrustVerifier,
    ) -> None:
        extension = bundle.manifest.extension
        digest = hashlib.sha256(archive).hexdigest()
        if digest != extension.archive_sha256:
            raise VerticalPackageValidationError("vertical package archive digest mismatch")
        if not verifier.verify(extension, archive):
            raise VerticalPackageValidationError("vertical package trust verification failed")
        _validate_bundle(bundle, host_reference_ids=self._host_reference_ids)


def _validate_bundle(
    bundle: VerticalPackageBundle,
    *,
    host_reference_ids: frozenset[str],
) -> None:
    manifest = bundle.manifest
    if bundle.descriptor.vertical_id != manifest.vertical_id:
        raise VerticalPackageValidationError("descriptor and manifest vertical ids differ")
    if bundle.descriptor.enabled:
        raise VerticalPackageValidationError("vertical packages must install disabled")
    if bundle.descriptor.default_mode is not Mode.SHADOW:
        raise VerticalPackageValidationError("vertical packages must start in shadow mode")
    expected_manifest_digest = _canonical_json_sha256(bundle.asset_manifest)
    if expected_manifest_digest != manifest.asset_manifest_sha256:
        raise VerticalPackageValidationError("vertical asset manifest digest mismatch")

    resource_manifest = _load_json_object(bundle.asset_manifest, "vertical asset manifest")
    if resource_manifest.get("schema_version") != "1.0.0":
        raise VerticalPackageValidationError("vertical asset manifest schema is unsupported")
    if resource_manifest.get("package_id") != manifest.vertical_id:
        raise VerticalPackageValidationError(
            "vertical asset manifest package id does not match the manifest"
        )
    if resource_manifest.get("package_version") != manifest.extension.version:
        raise VerticalPackageValidationError(
            "vertical asset manifest package version does not match the extension"
        )
    if resource_manifest.get("candidate_state") != "inert":
        raise VerticalPackageValidationError("vertical asset manifest candidates must remain inert")
    entries = resource_manifest.get("assets")
    if not isinstance(entries, list):
        raise VerticalPackageValidationError("vertical asset manifest assets must be an array")

    assets = bundle.assets
    _reject_duplicates(
        (asset.declaration.asset_id for asset in assets),
        "vertical asset id",
    )
    _reject_duplicates(
        (asset.declaration.resource_path for asset in assets),
        "vertical resource path",
    )
    _reject_duplicates(
        (asset.declaration.sha256 for asset in assets),
        "vertical asset digest",
    )
    actual_entries = [_asset_manifest_entry(asset) for asset in assets]
    if entries != actual_entries:
        raise VerticalPackageValidationError(
            "vertical asset declarations do not match the canonical resource manifest"
        )
    for asset in assets:
        actual_digest = hashlib.sha256(asset.content).hexdigest()
        if actual_digest != asset.declaration.sha256:
            raise VerticalPackageValidationError(
                f"vertical asset digest mismatch: {asset.declaration.asset_id}"
            )

    profile = _load_json_object(bundle.semantic_profile, "vertical semantic profile")
    if profile.get("canonical_sha256") != manifest.semantic_profile_sha256:
        raise VerticalPackageValidationError("vertical semantic profile digest mismatch")
    profile_payload = dict(profile)
    profile_payload.pop("canonical_sha256", None)
    profile_digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                profile_payload,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
    )
    if profile_digest != manifest.semantic_profile_sha256:
        raise VerticalPackageValidationError("vertical semantic profile content mismatch")
    if profile.get("ontology_release_digest") != manifest.ontology_release_range:
        raise VerticalPackageValidationError("vertical semantic profile ontology mismatch")
    authority_paths = _truthy_authority_paths(resource_manifest)
    authority_paths.extend(_truthy_authority_paths(profile))
    if authority_paths:
        raise VerticalPackageValidationError(
            "vertical package grants authority at " + ", ".join(authority_paths)
        )

    asset_ids = {asset.declaration.asset_id for asset in assets}
    asset_ids_by_path = {
        asset.declaration.resource_path: asset.declaration.asset_id for asset in assets
    }
    available_references = asset_ids | host_reference_ids
    for asset in assets:
        unknown = set(asset.declaration.references) - available_references
        if unknown:
            refs = ", ".join(sorted(unknown))
            raise VerticalPackageValidationError(
                f"vertical asset {asset.declaration.asset_id!r} has unknown references: {refs}"
            )
        _validate_asset_content(asset, asset_ids_by_path=asset_ids_by_path)

    required_providers = {provider.binding_id for provider in bundle.providers if provider.required}
    if required_providers != set(manifest.required_provider_bindings):
        raise VerticalPackageValidationError(
            "vertical provider declarations do not match manifest requirements"
        )
    _reject_duplicates(
        (provider.binding_id for provider in bundle.providers),
        "vertical provider binding",
    )

    capability_bundle = bundle.capability_bundle
    actual_capabilities = (
        {capability.capability_id for capability in capability_bundle.capabilities}
        if capability_bundle is not None
        else set()
    )
    if actual_capabilities != set(manifest.capability_ids):
        raise VerticalPackageValidationError(
            "vertical capability ids do not match the nested capability bundle"
        )


def _validate_install_collisions(
    bundle: VerticalPackageBundle,
    *,
    base_runtime: VerticalPackageRuntime,
    installed: Mapping[str, InstalledVerticalPackage],
) -> None:
    known_assets = list(base_runtime.assets.values())
    for item in installed.values():
        known_assets.extend(item.bundle.assets)
    known_ids = {asset.declaration.asset_id for asset in known_assets}
    known_digests = {asset.declaration.sha256 for asset in known_assets}
    for asset in bundle.assets:
        declaration = asset.declaration
        if declaration.asset_id in known_ids:
            raise VerticalPackageValidationError(
                f"duplicate installed asset id {declaration.asset_id!r}"
            )
        if declaration.sha256 in known_digests:
            raise VerticalPackageValidationError(
                f"duplicate installed asset digest {declaration.sha256!r}"
            )


def _validate_asset_content(
    asset: VerticalPackageAsset,
    *,
    asset_ids_by_path: Mapping[str, str],
) -> None:
    declaration = asset.declaration
    if not asset.content:
        raise VerticalPackageValidationError(
            f"vertical asset {declaration.asset_id!r} must not be empty"
        )
    if declaration.kind not in {VerticalAssetKind.RULE, VerticalAssetKind.WORKFLOW}:
        return
    try:
        payload = yaml.safe_load(asset.content)
    except yaml.YAMLError as exc:
        raise VerticalPackageValidationError(
            f"vertical asset {declaration.asset_id!r} contains invalid YAML"
        ) from exc
    if not isinstance(payload, dict):
        raise VerticalPackageValidationError(
            f"vertical asset {declaration.asset_id!r} must contain a YAML object"
        )
    expected_id = declaration.asset_id.split(":", 1)[1]
    identity_field = "id" if declaration.kind is VerticalAssetKind.RULE else "name"
    if payload.get(identity_field) != expected_id:
        raise VerticalPackageValidationError(
            f"vertical asset {declaration.asset_id!r} has a mismatched stable id"
        )
    if declaration.kind is VerticalAssetKind.WORKFLOW:
        if payload.get("default_mode") != "shadow":
            raise VerticalPackageValidationError("vertical workflows must remain shadow-first")
        expected_references = {
            f"action:{step.get('action_type_ref')}"
            for step in payload.get("steps", ())
            if isinstance(step, dict) and step.get("action_type_ref")
        }
    else:
        expected_references = set()
        check_logic = payload.get("check_logic")
        if isinstance(check_logic, dict) and isinstance(check_logic.get("reference"), str):
            policy_id = asset_ids_by_path.get(check_logic["reference"])
            if policy_id is None:
                raise VerticalPackageValidationError(
                    f"vertical rule {declaration.asset_id!r} references an unknown policy path"
                )
            expected_references.add(policy_id)
        remediation = payload.get("remediation")
        if isinstance(remediation, dict) and isinstance(remediation.get("template_ref"), str):
            remediation_id = asset_ids_by_path.get(remediation["template_ref"])
            if remediation_id is None:
                raise VerticalPackageValidationError(
                    f"vertical rule {declaration.asset_id!r} references an unknown remediation path"
                )
            expected_references.add(remediation_id)
        if isinstance(payload.get("remediates"), str):
            expected_references.add(f"action:{payload['remediates']}")
    if not expected_references.issubset(declaration.references):
        raise VerticalPackageValidationError(
            f"vertical asset {declaration.asset_id!r} omits content cross-references"
        )


def _derive_availability(
    bundle: VerticalPackageBundle,
    *,
    host_version: str,
    ontology_release_digest: str,
    provider_bindings: frozenset[str],
) -> VerticalPackageAvailability:
    reasons: list[str] = []
    extension = bundle.manifest.extension
    host = _version_tuple(host_version)
    if host < _version_tuple(extension.min_host_version) or (
        extension.max_host_version is not None and host > _version_tuple(extension.max_host_version)
    ):
        reasons.append("host_incompatible")
    if bundle.manifest.ontology_release_range != ontology_release_digest:
        reasons.append("ontology_incompatible")
    for binding_id in sorted(set(bundle.manifest.required_provider_bindings) - provider_bindings):
        reasons.append(f"missing_provider:{binding_id}")
    return VerticalPackageAvailability(available=not reasons, reasons=tuple(reasons))


def _asset_manifest_entry(asset: VerticalPackageAsset) -> dict[str, Any]:
    declaration = asset.declaration
    return {
        "id": declaration.asset_id,
        "kind": declaration.kind.value,
        "path": declaration.resource_path,
        "references": list(declaration.references),
        "sha256": declaration.sha256,
    }


def _canonical_json_sha256(content: bytes) -> str:
    value = _load_json_object(content, "vertical asset manifest")
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_json_object(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerticalPackageValidationError(f"{label} must contain valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise VerticalPackageValidationError(f"{label} must contain a JSON object")
    return value


def _reject_duplicates(values: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        joined = ", ".join(sorted(duplicates))
        raise VerticalPackageValidationError(f"duplicate {label}: {joined}")


def _truthy_authority_paths(value: Any, path: str = "$") -> list[str]:
    failures: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in _FORBIDDEN_AUTHORITY_FIELDS and child not in (False, None):
                failures.append(child_path)
            failures.extend(_truthy_authority_paths(child, child_path))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            failures.extend(_truthy_authority_paths(child, f"{path}[{index}]"))
    return failures


def _require_package(
    installed: Mapping[str, InstalledVerticalPackage],
    extension_id: str,
) -> InstalledVerticalPackage:
    try:
        return installed[extension_id]
    except KeyError as exc:
        raise VerticalPackageLifecycleError(
            f"vertical package {extension_id!r} is not installed"
        ) from exc


def _version_tuple(value: str) -> tuple[int, int, int]:
    parts = value.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError(f"version {value!r} must use MAJOR.MINOR.PATCH")
    return int(parts[0]), int(parts[1]), int(parts[2])


def _is_n_minus_one(previous: str, candidate: str) -> bool:
    previous_version = _version_tuple(previous)
    candidate_version = _version_tuple(candidate)
    return (
        candidate_version[:2] == previous_version[:2]
        and candidate_version[2] == previous_version[2] + 1
    )


__all__ = ["VerticalPackageManager"]
