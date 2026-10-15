"""Strict loader for FDAI-owned code-security analysis rules."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from fdai.core.security.code_findings.analysis_contracts import CodeSecurityRuleSpec
from fdai.rule_catalog.code_security import CodeSecurityCatalogError


def load_analysis_rules(root: Path) -> tuple[CodeSecurityRuleSpec, ...]:
    """Load all versioned owned-analysis rules in stable id order."""
    directory = root / "analysis-rules"
    paths = sorted((*directory.glob("*.yaml"), *directory.glob("*.yml")))
    if not paths:
        raise CodeSecurityCatalogError("code-security analysis rule catalog is empty")
    rules: list[CodeSecurityRuleSpec] = []
    for path in paths:
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
            rules.append(CodeSecurityRuleSpec.model_validate(document))
        except (OSError, yaml.YAMLError, ValidationError) as exc:
            raise CodeSecurityCatalogError(
                f"invalid code-security analysis rule {path.name}: {exc}"
            ) from exc
    identities = [(rule.rule_id, rule.version) for rule in rules]
    if len(identities) != len(set(identities)):
        raise CodeSecurityCatalogError("duplicate code-security analysis rule identity")
    return tuple(sorted(rules, key=lambda rule: (rule.rule_id, rule.version)))


__all__ = ["load_analysis_rules"]
