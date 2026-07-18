"""Deep validators for catalog-owned data."""

from __future__ import annotations

import re
from collections import Counter

import yaml
from jsonschema import Draft202012Validator, SchemaError
from jsonschema.exceptions import ValidationError

from .common import (
    ACTION_TYPES_DIR,
    PROFILES_DIR,
    REMEDIATION_DIR,
    REPO_ROOT,
    RISK_CLASSIFICATION,
    Runner,
    StepResult,
    iter_rule_files,
    load_schema,
    load_yaml,
)

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ZERO_SHA = "0" * 40
_FDAI_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


def _action_type_ids() -> set[str]:
    action_type_ids: set[str] = set()
    if ACTION_TYPES_DIR.is_dir():
        for path in ACTION_TYPES_DIR.glob("*.yaml"):
            data = load_yaml(path)
            if isinstance(data, dict) and "name" in data:
                action_type_ids.add(str(data["name"]))
    return action_type_ids


def _schema_finding(path: object, error: ValidationError) -> str:
    where = ".".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{path}: schema[{where}]: {error.message}"


def step_rule_deep(runner: Runner) -> StepResult:
    rule_validator = load_schema("rule/schema.json")
    action_type_ids = _action_type_ids()
    findings: list[str] = []
    ids: Counter[str] = Counter()
    checked = 0
    provenance_placeholder_hits = 0
    bad_id_pattern = 0
    for path in iter_rule_files():
        data = load_yaml(path)
        relative_path = path.relative_to(REPO_ROOT)
        if data is None:
            findings.append(f"{relative_path}: file is empty")
            continue
        errors = sorted(rule_validator.iter_errors(data), key=lambda error: list(error.path))
        if errors:
            findings.append(_schema_finding(relative_path, errors[0]))
            continue
        rule_id = str(data.get("id", ""))
        ids[rule_id] += 1
        if not _FDAI_ID_RE.fullmatch(rule_id):
            bad_id_pattern += 1
            findings.append(f"{relative_path}: id {rule_id!r} fails FDAI id regex")
        provenance = data.get("provenance") or {}
        resolved_ref = str(provenance.get("resolved_ref", ""))
        relative = str(relative_path)
        if relative.startswith("rule-catalog/collected/"):
            if resolved_ref == _ZERO_SHA:
                provenance_placeholder_hits += 1
                findings.append(f"{relative}: provenance.resolved_ref is the all-zero placeholder")
            elif not _SHA_RE.fullmatch(resolved_ref):
                findings.append(
                    f"{relative}: provenance.resolved_ref {resolved_ref!r}"
                    " is not a 40-hex commit SHA"
                )
        action_type = (data.get("remediation") or {}).get("action_type_id")
        if action_type and str(action_type) not in action_type_ids:
            findings.append(
                f"{relative}: remediation.action_type_id {action_type!r} not found in action-types/"
            )
        checked += 1
    duplicates = {key: value for key, value in ids.items() if value > 1}
    if duplicates:
        findings.append(f"duplicate rule ids across catalog: {sorted(duplicates)[:20]}")
    return StepResult(
        name="rule_deep",
        ok=not findings,
        duration_s=0.0,
        findings=findings,
        stats={
            "checked": checked,
            "unique_ids": len(ids),
            "duplicate_ids": len(duplicates),
            "provenance_placeholder_hits": provenance_placeholder_hits,
            "bad_id_pattern": bad_id_pattern,
        },
    )


def step_profile_deep(runner: Runner) -> StepResult:
    from fdai.core.rule_catalog_profiles import ProfileRegistry, ProfileResolutionError

    profile_schema = load_schema("profile/schema.json")
    known_rule_ids: set[str] = set()
    for path in iter_rule_files():
        data = load_yaml(path)
        if isinstance(data, dict) and "id" in data:
            known_rule_ids.add(str(data["id"]))
    findings: list[str] = []
    schema_bad = 0
    resolve_bad = 0
    for path in sorted(PROFILES_DIR.rglob("*.yaml")):
        data = load_yaml(path)
        if data is None:
            continue
        errors = sorted(profile_schema.iter_errors(data), key=lambda error: list(error.path))
        if errors:
            schema_bad += 1
            findings.append(_schema_finding(path.relative_to(REPO_ROOT), errors[0]))
    try:
        registry = ProfileRegistry.from_directories(upstream=PROFILES_DIR)
    except ProfileResolutionError as exc:
        return StepResult(
            name="profile_deep", ok=False, duration_s=0.0, findings=[f"registry load: {exc}"]
        )
    checked = 0
    for profile in registry.all():
        try:
            registry.resolve(profile.id, known_rule_ids=known_rule_ids)
        except ProfileResolutionError as exc:
            resolve_bad += 1
            findings.append(f"{profile.id}: {exc}")
        checked += 1
    known_profile_ids = {profile.id for profile in registry.all()}
    for profile in registry.all():
        for parent in profile.extends:
            if parent not in known_profile_ids:
                findings.append(f"{profile.id}: extends unknown profile {parent!r}")
    return StepResult(
        name="profile_deep",
        ok=not findings,
        duration_s=0.0,
        findings=findings,
        stats={
            "profiles_checked": checked,
            "known_rule_ids": len(known_rule_ids),
            "schema_bad": schema_bad,
            "resolve_bad": resolve_bad,
        },
    )


def step_action_type_deep(runner: Runner) -> StepResult:
    if not ACTION_TYPES_DIR.is_dir():
        return StepResult(
            name="action_type_deep",
            ok=True,
            duration_s=0.0,
            skipped=True,
            skipped_reason="action-types directory not present",
        )
    action_type_schema = load_schema("ontology/action-type.json")
    findings: list[str] = []
    ids: Counter[str] = Counter()
    shadow_without_gate = 0
    bad_argument_schema = 0
    checked = 0
    for path in sorted(ACTION_TYPES_DIR.glob("*.yaml")):
        try:
            data = load_yaml(path)
        except yaml.YAMLError as exc:
            findings.append(f"{path.relative_to(REPO_ROOT)}: not valid YAML: {exc}")
            continue
        if data is None:
            continue
        errors = sorted(action_type_schema.iter_errors(data), key=lambda error: list(error.path))
        if errors:
            findings.append(_schema_finding(path.relative_to(REPO_ROOT), errors[0]))
            continue
        name = data.get("name")
        if not isinstance(name, str):
            findings.append(f"{path.relative_to(REPO_ROOT)}: missing string `name` field")
            continue
        ids[name] += 1
        if data.get("default_mode") == "shadow" and not data.get("promotion_gate"):
            shadow_without_gate += 1
            findings.append(
                f"{path.relative_to(REPO_ROOT)}: default_mode=shadow requires a promotion_gate"
            )
        argument_schema = data.get("argument_schema")
        if argument_schema is not None:
            try:
                Draft202012Validator.check_schema(argument_schema)
            except SchemaError as exc:
                bad_argument_schema += 1
                findings.append(
                    f"{path.relative_to(REPO_ROOT)}: argument_schema invalid: {exc.message}"
                )
        checked += 1
    duplicates = {key: value for key, value in ids.items() if value > 1}
    if duplicates:
        findings.append(f"duplicate action-type ids: {sorted(duplicates)}")
    return StepResult(
        name="action_type_deep",
        ok=not findings,
        duration_s=0.0,
        findings=findings,
        stats={
            "checked": checked,
            "unique_ids": len(ids),
            "shadow_without_gate": shadow_without_gate,
            "bad_argument_schema": bad_argument_schema,
        },
    )


def step_remediation_deep(runner: Runner) -> StepResult:
    if not REMEDIATION_DIR.is_dir():
        return StepResult(
            name="remediation_deep",
            ok=True,
            duration_s=0.0,
            skipped=True,
            skipped_reason="remediation directory not present",
        )
    action_type_ids = _action_type_ids()
    findings: list[str] = []
    checked = 0
    for path in sorted(REMEDIATION_DIR.rglob("*.yaml")):
        data = load_yaml(path)
        if data is None:
            continue
        references: list[str] = []
        if isinstance(data, dict):
            top = data.get("action_type_id")
            if isinstance(top, str):
                references.append(top)
            for step in data.get("steps") or []:
                if isinstance(step, dict) and isinstance(step.get("action_type_id"), str):
                    references.append(step["action_type_id"])
        for reference in references:
            if reference not in action_type_ids:
                findings.append(
                    f"{path.relative_to(REPO_ROOT)}: unknown action_type_id {reference!r}"
                )
        checked += 1
    return StepResult(
        name="remediation_deep",
        ok=not findings,
        duration_s=0.0,
        findings=findings,
        stats={"checked": checked, "known_action_types": len(action_type_ids)},
    )


def step_risk_classification(runner: Runner) -> StepResult:
    if not RISK_CLASSIFICATION.is_file():
        return StepResult(
            name="risk_classification",
            ok=True,
            duration_s=0.0,
            skipped=True,
            skipped_reason="risk-classification.yaml not present",
        )
    data = load_yaml(RISK_CLASSIFICATION)
    findings: list[str] = []
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        return StepResult(
            name="risk_classification",
            ok=False,
            duration_s=0.0,
            findings=["risk-classification.yaml: missing or invalid `rules` list"],
        )
    order = {"deny": 0, "hil": 1, "auto": 2}
    previous = -1
    for entry in data["rules"]:
        decision = str(entry.get("decision", ""))
        rank = order.get(decision, 3)
        if rank < previous:
            findings.append(
                f"{entry.get('id')}: decision {decision!r} appears after a weaker one"
                " (must be deny -> hil -> auto)"
            )
        previous = max(previous, rank)
    return StepResult(
        name="risk_classification",
        ok=not findings,
        duration_s=0.0,
        findings=findings,
        stats={"rules": len(data["rules"])},
    )
