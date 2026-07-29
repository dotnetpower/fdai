"""Deep validators for catalog-owned data."""

from __future__ import annotations

import re
from collections import Counter

import yaml
from jsonschema import Draft202012Validator, SchemaError
from jsonschema.exceptions import ValidationError

from .common import (
    ACTION_TYPES_DIR,
    ARCHITECTURE_REVIEW,
    BEST_PRACTICES_DIR,
    CATALOG_ROOT,
    PROBES_DIR,
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


def step_best_practice_deep(runner: Runner) -> StepResult:
    """Validate Best Practice controls, typed references, and WAF initiatives."""

    from fdai.rule_catalog.schema.best_practice_catalog import (
        BestPracticeCatalogError,
        load_best_practice_catalog,
    )
    from fdai.rule_catalog.schema.governance_catalog import load_governance_catalog
    from fdai.rule_catalog.schema.governance_loader import GovernanceLoadError
    from fdai.rule_catalog.schema.probe import load_probe_catalog, probe_ids
    from fdai.shared.contracts.models import RequirementKind

    rule_versions: dict[str, str] = {}
    for path in iter_rule_files():
        data = load_yaml(path)
        if isinstance(data, dict) and "id" in data and "version" in data:
            rule_versions[str(data["id"])] = str(data["version"])

    raw = load_yaml(ARCHITECTURE_REVIEW)
    if not isinstance(raw, dict) or not isinstance(raw.get("architecture_review"), dict):
        return StepResult(
            name="best_practice_deep",
            ok=False,
            duration_s=0.0,
            findings=["config/architecture-review.yaml: architecture_review must be a mapping"],
        )
    review = raw["architecture_review"]
    gate = review.get("production_gate")
    if not isinstance(gate, dict):
        return StepResult(
            name="best_practice_deep",
            ok=False,
            duration_s=0.0,
            findings=["config/architecture-review.yaml: production_gate must be a mapping"],
        )
    artifacts = review.get("artifacts")
    if not isinstance(artifacts, list):
        artifacts = []
    artifact_ids = {
        str(artifact["id"])
        for artifact in artifacts
        if isinstance(artifact, dict) and "id" in artifact
    }
    evidence_ids = {str(item) for item in gate.get("required_evidence", ())}
    owner_ids = {str(item) for item in gate.get("required_owner_slots", ())}
    registries = {
        RequirementKind.RULE: set(rule_versions),
        RequirementKind.PROBE: probe_ids(load_probe_catalog(PROBES_DIR)),
        RequirementKind.ARTIFACT: artifact_ids | evidence_ids,
        RequirementKind.METRIC: evidence_ids,
        RequirementKind.DRILL: evidence_ids,
        RequirementKind.APPROVAL: owner_ids,
    }

    findings: list[str] = []
    controls = ()
    try:
        controls = load_best_practice_catalog(BEST_PRACTICES_DIR, known_refs=registries)
    except BestPracticeCatalogError as exc:
        findings.extend(f"{issue.key}: {issue.message}" for issue in exc.issues)
    expected_controls = {f"RE:{number:02d}" for number in range(1, 11)} | {
        f"OE:{number:02d}" for number in range(1, 12)
    }
    actual_controls = {control.control_id for control in controls}
    if actual_controls != expected_controls:
        findings.append("azure-waf controls differ from the required RE:01-10 and OE:01-11 set")

    rule_sets = ()
    try:
        governance = load_governance_catalog(
            CATALOG_ROOT,
            known_rule_versions=rule_versions,
        )
        rule_sets = governance.rule_sets
    except GovernanceLoadError as exc:
        findings.extend(f"{issue.key}: {issue.message}" for issue in exc.issues)
    rule_set_ids = {rule_set.id for rule_set in rule_sets}
    required_rule_sets = {"azure-waf.reliability", "azure-waf.operational-excellence"}
    if not required_rule_sets <= rule_set_ids:
        findings.append("missing Azure WAF Reliability or Operational Excellence rule-set")

    return StepResult(
        name="best_practice_deep",
        ok=not findings,
        duration_s=0.0,
        findings=findings,
        stats={
            "controls_checked": len(controls),
            "rule_sets_checked": len(rule_sets),
            "known_rule_ids": len(rule_versions),
        },
    )


def step_mcsb_deep(runner: Runner) -> StepResult:
    """Validate versioned MCSB controls and every implementation cross-reference."""

    from fdai.delivery.azure.security_posture_mcsb import MCSB_CONTROLS_BY_OBSERVATION
    from fdai.rule_catalog.schema.mcsb_catalog import McsbCatalogError, load_mcsb_catalogs

    rule_sources: dict[str, str] = {}
    for path in iter_rule_files():
        data = load_yaml(path)
        if isinstance(data, dict) and "id" in data and "source" in data:
            rule_sources[str(data["id"])] = str(data["source"])
    profile_counts: dict[str, int] = {}
    for path in sorted((PROFILES_DIR / "collected").glob("*.yaml")):
        data = load_yaml(path)
        if isinstance(data, dict) and "id" in data:
            rules = data.get("rules")
            profile_counts[str(data["id"])] = len(rules) if isinstance(rules, list) else 0
    review_raw = load_yaml(ARCHITECTURE_REVIEW)
    manual_evidence: set[str] = set()
    if isinstance(review_raw, dict) and isinstance(review_raw.get("architecture_review"), dict):
        review = review_raw["architecture_review"]
        artifacts = review.get("artifacts")
        if isinstance(artifacts, list):
            manual_evidence.update(
                str(artifact["id"])
                for artifact in artifacts
                if isinstance(artifact, dict) and "id" in artifact
            )
        gate = review.get("production_gate")
        if isinstance(gate, dict) and isinstance(gate.get("required_evidence"), list):
            manual_evidence.update(str(value) for value in gate["required_evidence"])

    findings: list[str] = []
    catalogs = ()
    try:
        catalogs = load_mcsb_catalogs(
            CATALOG_ROOT / "compliance" / "mcsb",
            known_rule_ids=set(rule_sources),
            known_policy_profiles=profile_counts,
            known_runtime_observation_ids=set(MCSB_CONTROLS_BY_OBSERVATION),
            known_manual_evidence_refs=manual_evidence,
        )
    except (FileNotFoundError, McsbCatalogError) as exc:
        findings.append(str(exc))
    by_version = {catalog.benchmark_version: catalog for catalog in catalogs}
    if set(by_version) != {"v1", "v2-preview"}:
        findings.append("MCSB catalogs MUST contain separate v1 and v2-preview versions")
    v1 = by_version.get("v1")
    if v1 is not None:
        if len(v1.controls) != 86:
            findings.append(f"MCSB v1 MUST contain 86 controls, found {len(v1.controls)}")
        expected_coverage = {"manual": 9, "partial": 16, "unmapped": 61}
        if v1.coverage_counts() != expected_coverage:
            findings.append(
                f"MCSB v1 coverage differs: {v1.coverage_counts()} != {expected_coverage}"
            )
        mapped_rules = {rule_id for mapping in v1.mappings for rule_id in mapping.rule_ids}
        expected_rules = {rule_id for rule_id, source in rule_sources.items() if source == "mcsb"}
        if mapped_rules != expected_rules:
            findings.append("MCSB v1 crosswalk does not cover every curated MCSB rule exactly")
    v2 = by_version.get("v2-preview")
    if v2 is not None and (v2.control_import_status != "metadata_only" or v2.controls):
        findings.append("MCSB v2 preview MUST remain metadata-only until controls are imported")
    return StepResult(
        name="mcsb_deep",
        ok=not findings,
        duration_s=0.0,
        findings=findings,
        stats={
            "versions_checked": len(catalogs),
            "controls_checked": sum(len(catalog.controls) for catalog in catalogs),
            "mcsb_rules_checked": sum(source == "mcsb" for source in rule_sources.values()),
            "runtime_observations_checked": len(MCSB_CONTROLS_BY_OBSERVATION),
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
