"""Land parsed Azure Policy built-in Rules in the collected catalog tree.

The collector snapshots a pinned ``Azure/azure-policy`` revision and the ``azure-policy-json``
parser turns it into Rule mappings. This stage writes those mappings to
``rule-catalog/collected/azure-builtin/<folder>/<rule-id>.yaml``, stamping the pinned commit as
``resolved_ref`` and the snapshot time as ``retrieved_at`` so a rerun on the same snapshot writes
identical bytes. ``content_hash`` stays the parser's SHA-256 of the exact definition bytes.

Rule identity is keyed by the Azure Policy definition name (its GUID). A policy that already has a
collected Rule keeps that Rule's id and path, so a re-collection never renames a Rule. A new
policy takes the parser's id; when that id or path collides with another Rule, the policy isn't
landed and is reported instead, because choosing between them would invent an identity.

Every landed document must pass the strict Rule JSON Schema and the ``Rule`` model before any
file is written; one invalid Rule fails the whole run. A collected Rule whose policy is absent
from the new snapshot is kept and reported as withdrawn, because the collection design retires a
removed control with a version bump instead of dropping it. Landed Rules stay inert ``expression``
Rules; nothing here activates or translates them.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Final

import yaml
from jsonschema import Draft202012Validator

from fdai.rule_catalog.pipeline.parse.parser import ParsedRule
from fdai.shared.contracts.models import Rule
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

_REVISION: Final = re.compile(r"^[0-9a-f]{40}$")
_PLACEHOLDER_REVISION: Final = "0" * 40
_MAX_FILE_STEM: Final = 120


class AzurePolicyLandingError(ValueError):
    """The parsed Rules can't be landed deterministically."""


@dataclass(frozen=True, slots=True)
class AzurePolicyLandingReport:
    """What one landing pass wrote, kept, and removed."""

    written: int
    unchanged: int
    withdrawn: tuple[str, ...] = ()
    skipped_collisions: tuple[str, ...] = ()

    @property
    def landed(self) -> int:
        return self.written + self.unchanged


def collected_rule_path(rule: ParsedRule) -> PurePosixPath:
    """Return the Rule's path relative to the collected tree root."""

    parts = PurePosixPath(rule.origin).parts
    rule_id = rule.raw.get("id")
    if len(parts) < 2 or not isinstance(rule_id, str) or not rule_id:
        raise AzurePolicyLandingError(f"{rule.origin}: no category folder or Rule id")
    folder = re.sub(r"[^a-z0-9]", "-", parts[0].lower())
    return PurePosixPath(folder, rule_id.replace(".", "_")[:_MAX_FILE_STEM] + ".yaml")


def land_azure_policy_rules(
    rules: Sequence[ParsedRule],
    *,
    resolved_ref: str,
    retrieved_at: datetime,
    output_root: Path,
) -> AzurePolicyLandingReport:
    """Validate and write every parsed Rule with pinned provenance; report withdrawn policies."""

    if _REVISION.fullmatch(resolved_ref) is None or resolved_ref == _PLACEHOLDER_REVISION:
        raise AzurePolicyLandingError("resolved_ref MUST be a pinned 40-character commit SHA")
    if retrieved_at.tzinfo is None:
        raise AzurePolicyLandingError("retrieved_at MUST be timezone-aware")
    if not rules:
        raise AzurePolicyLandingError("refusing to land an empty Azure Policy collection")
    stamp = retrieved_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    existing = _existing_identities(output_root)
    planned: dict[str, tuple[ParsedRule, str, PurePosixPath]] = {}
    fresh: list[tuple[ParsedRule, str, PurePosixPath]] = []
    for rule in rules:
        name = _policy_name(rule)
        if name in planned or any(name == _policy_name(item[0]) for item in fresh):
            raise AzurePolicyLandingError(f"{rule.origin}: policy {name} was parsed twice")
        if name in existing:
            rule_id, relative = existing[name]
            planned[name] = (rule, rule_id, relative)
        else:
            fresh.append((rule, str(rule.raw.get("id")), collected_rule_path(rule)))
    # Withdrawn Rules stay on disk, so their ids and paths stay claimed too.
    claimed_ids = {rule_id for rule_id, _ in existing.values()}
    claimed_paths = {relative for _, relative in existing.values()}
    if len(claimed_ids) != len(existing) or len(claimed_paths) != len(existing):
        raise AzurePolicyLandingError("existing collected Rules share an id or a path")
    skipped: list[str] = []
    for index, (rule, rule_id, relative) in enumerate(fresh):
        others = fresh[:index] + fresh[index + 1 :]
        if (
            rule_id in claimed_ids
            or relative in claimed_paths
            or any(item[1] == rule_id or item[2] == relative for item in others)
        ):
            skipped.append(_policy_name(rule))
            continue
        planned[_policy_name(rule)] = (rule, rule_id, relative)
    validator = Draft202012Validator(dict(PackageResourceSchemaRegistry().get("rule")))
    documents: dict[PurePosixPath, str] = {}
    for rule, rule_id, relative in planned.values():
        raw: dict[str, Any] = copy.deepcopy(dict(rule.raw))
        raw["id"] = rule_id
        provenance = raw.get("provenance")
        if not isinstance(provenance, dict):
            raise AzurePolicyLandingError(f"{rule.origin}: Rule has no provenance")
        provenance["resolved_ref"] = resolved_ref
        provenance["retrieved_at"] = stamp
        errors = sorted(error.message for error in validator.iter_errors(raw))
        if errors:
            raise AzurePolicyLandingError(f"{rule.origin}: Rule schema violation: {errors[0]}")
        try:
            Rule.model_validate(raw)
        except ValueError as exc:
            raise AzurePolicyLandingError(f"{rule.origin}: invalid Rule: {exc}") from exc
        documents[relative] = yaml.safe_dump(raw, sort_keys=False)

    written = unchanged = 0
    for relative, text in sorted(documents.items()):
        target = output_root.joinpath(*relative.parts)
        if target.is_file() and target.read_text(encoding="utf-8") == text:
            unchanged += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        written += 1
    return AzurePolicyLandingReport(
        written=written,
        unchanged=unchanged,
        withdrawn=tuple(sorted(set(existing) - set(planned) - set(skipped))),
        skipped_collisions=tuple(sorted(skipped)),
    )


def _policy_name(rule: ParsedRule) -> str:
    parameters = rule.raw.get("parameters")
    name = parameters.get("azure_policy_name") if isinstance(parameters, dict) else None
    if not isinstance(name, str) or not name:
        raise AzurePolicyLandingError(f"{rule.origin}: Rule has no azure_policy_name")
    return name


def _existing_identities(output_root: Path) -> dict[str, tuple[str, PurePosixPath]]:
    """Map each already collected policy name to its Rule id and tree-relative path."""

    identities: dict[str, tuple[str, PurePosixPath]] = {}
    if not output_root.is_dir():
        return identities
    for path in sorted(output_root.rglob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        parameters = document.get("parameters") if isinstance(document, dict) else None
        name = parameters.get("azure_policy_name") if isinstance(parameters, dict) else None
        rule_id = document.get("id") if isinstance(document, dict) else None
        if not isinstance(name, str) or not isinstance(rule_id, str):
            raise AzurePolicyLandingError(f"{path}: collected Rule has no id or policy name")
        if name in identities:
            raise AzurePolicyLandingError(f"{path}: policy {name} is collected twice")
        identities[name] = (rule_id, PurePosixPath(path.relative_to(output_root).as_posix()))
    return identities


__all__ = [
    "AzurePolicyLandingError",
    "AzurePolicyLandingReport",
    "collected_rule_path",
    "land_azure_policy_rules",
]
