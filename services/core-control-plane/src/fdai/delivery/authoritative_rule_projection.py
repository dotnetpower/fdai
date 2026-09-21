"""Build deterministic active and collected Rule projections for Operator."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from fdai.shared.contracts.models import Rule

MAX_BODY_BYTES = 512_000
_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def rule_snapshot(
    active_rules: Sequence[Rule],
    *,
    collected_rules: Sequence[Rule],
    policies_root: Path,
    remediation_root: Path,
) -> dict[str, object]:
    entries = [
        *((rule, "active") for rule in active_rules),
        *((rule, "collected") for rule in collected_rules),
    ]
    ordered = sorted(
        entries,
        key=lambda entry: (
            -_SEVERITY_RANK.get(entry[0].severity.value, 0),
            entry[0].id,
            entry[1],
        ),
    )
    summaries = [_rule_summary(rule, origin=origin) for rule, origin in ordered]
    details = {
        f"{origin}:{rule.id}": _rule_detail(
            rule,
            origin=origin,
            policies_root=policies_root,
            remediation_root=remediation_root,
        )
        for rule, origin in sorted(entries, key=lambda entry: (entry[1], entry[0].id))
    }
    return {"rules": summaries, "details": details}


def load_collected_rules(root: Path) -> tuple[Rule, ...]:
    """Load the inert reference corpus without active-catalog cross-references."""
    loaded: list[Rule] = []
    for path in sorted(root.rglob("*.yaml")):
        try:
            loaded.append(Rule.model_validate(_yaml_mapping(path)))
        except (OSError, ValueError, yaml.YAMLError) as exc:
            raise RuntimeError(f"invalid collected Rule document: {path}") from exc
    return tuple(loaded)


def _rule_summary(rule: Rule, *, origin: str) -> dict[str, object]:
    provenance = rule.provenance
    return {
        "id": rule.id,
        "origin": origin,
        "version": str(rule.version),
        "source": rule.source.value,
        "severity": rule.severity.value,
        "category": rule.category.value,
        "resource_type": rule.resource_type,
        "check_logic": rule.check_logic.model_dump(mode="json"),
        "remediation": rule.remediation.model_dump(mode="json"),
        "remediates": rule.remediates,
        "provenance": {
            "source_url": provenance.source_url,
            "license": provenance.license,
            "redistribution": provenance.redistribution.value,
        },
    }


def _rule_detail(
    rule: Rule,
    *,
    origin: str,
    policies_root: Path,
    remediation_root: Path,
) -> dict[str, object]:
    check_logic_body = _read_reference(
        policies_root,
        rule.check_logic.reference,
        prefix="policies/",
    )
    detail = _rule_summary(rule, origin=origin)
    detail.update(
        {
            "schema_version": str(rule.schema_version),
            "alternatives": list(rule.alternatives),
            "parameters": dict(rule.parameters),
            "applies_to": {"resource_types": list(rule.applies_to)},
            "check_logic_body": check_logic_body,
            "remediation_body": _read_reference(
                remediation_root,
                rule.remediation.template_ref,
                prefix="remediation/",
            ),
            "explanation": _rule_explanation(rule, check_logic_body),
            "provenance": rule.provenance.model_dump(mode="json"),
        }
    )
    return detail


def _rule_explanation(rule: Rule, check_logic_body: str | None) -> dict[str, object]:
    metadata = _rego_metadata(check_logic_body) if check_logic_body else None
    if metadata and (metadata.get("title") or metadata.get("description")):
        return {
            "title": metadata.get("title"),
            "description": metadata.get("description"),
            "source": "rego_metadata",
            "details": {},
        }
    parameters = rule.parameters
    if "azure_policy_display_name" in parameters:
        return {
            "title": parameters.get("azure_policy_display_name"),
            "description": None,
            "source": "azure_policy",
            "details": {
                key: parameters[key]
                for key in ("azure_policy_effect_default", "azure_policy_category")
                if parameters.get(key) is not None
            },
        }
    if "kube_bench_id" in parameters:
        return {
            "title": (
                f"CIS {parameters.get('kube_bench_ruleset', '')} "
                f"{parameters.get('kube_bench_id', '')}"
            ).strip(),
            "description": None,
            "source": "kube_bench",
            "details": {
                key: parameters[key]
                for key in ("kube_bench_audit", "kube_bench_scored")
                if parameters.get(key) is not None
            },
        }
    return {"title": None, "description": None, "source": None, "details": {}}


def _rego_metadata(body: str) -> Mapping[str, Any] | None:
    lines = body.splitlines()
    try:
        start = next(
            index + 1
            for index, line in enumerate(lines)
            if line.strip() in {"# METADATA", "#METADATA"}
        )
    except StopIteration:
        return None
    collected: list[str] = []
    for line in lines[start:]:
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            break
        content = stripped[1:]
        collected.append(content[1:] if content.startswith(" ") else content)
    if not collected:
        return None
    try:
        parsed = yaml.safe_load("\n".join(collected))
    except yaml.YAMLError:
        return None
    return parsed if isinstance(parsed, Mapping) else None


def _read_reference(root: Path, reference: str, *, prefix: str) -> str | None:
    if not reference.startswith(prefix):
        return None
    relative = Path(reference.removeprefix(prefix))
    if relative.is_absolute() or ".." in relative.parts:
        return None
    root_resolved = root.resolve()
    candidate = (root_resolved / relative).resolve()
    if not candidate.is_relative_to(root_resolved) or not candidate.is_file():
        return None
    try:
        with candidate.open("rb") as stream:
            raw = stream.read(MAX_BODY_BYTES + 1)
    except OSError:
        return None
    truncated = len(raw) > MAX_BODY_BYTES
    try:
        body = raw[:MAX_BODY_BYTES].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"catalog reference MUST be valid UTF-8: {reference}") from exc
    return body + "\n... [truncated]" if truncated else body


def _yaml_mapping(path: Path) -> Mapping[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise ValueError(f"expected YAML mapping: {path}")
    return loaded


__all__ = ["load_collected_rules", "rule_snapshot"]
