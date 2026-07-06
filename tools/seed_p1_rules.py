#!/usr/bin/env python3
"""One-shot seed generator for P1 rule catalog.

Reads ``tools/seed_p1_manifest.yaml`` and emits, for every entry:

- ``rule-catalog/catalog/<id>.yaml`` - normalized rule
- ``policies/<policy_dir>/<policy_stem>.rego`` - deterministic check
- ``rule-catalog/remediation/<template_dir>/<template_stem>.tftpl`` - IaC patch

Intent: bootstrap the P1 seed catalog in bulk, then leave the generator
behind as a machine-readable example of what a rule PR looks like (see
[rule-catalog/RULE_AUTHORING_GUIDE.md](../rule-catalog/RULE_AUTHORING_GUIDE.md)).
The pipeline never runs this at runtime - every downstream consumer
reads the emitted YAML / rego / tftpl files directly. Re-runs are
idempotent (existing files are overwritten to match the manifest).

Not intended for extension; new rules go through the manual authoring
flow described in the guide.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path(__file__).resolve().parent / "seed_p1_manifest.yaml"

CATALOG_ROOT = REPO_ROOT / "rule-catalog" / "catalog"
POLICIES_ROOT = REPO_ROOT / "policies"
REMEDIATION_ROOT = REPO_ROOT / "rule-catalog" / "remediation"

DEFAULT_HASH = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
DEFAULT_REF = "0000000000000000000000000000000000000000"


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not body.endswith("\n"):
        body = body + "\n"
    path.write_text(body, encoding="utf-8")


def _yaml_dump(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False, width=100)


def _rule_yaml(entry: dict[str, Any]) -> str:
    rule: dict[str, Any] = {
        "schema_version": "1.0.0",
        "id": entry["id"],
        "version": entry.get("version", "1.0.0"),
        "source": entry["source"],
        "severity": entry["severity"],
        "category": entry["category"],
        "resource_type": entry["resource_type"],
        "check_logic": {
            "kind": "rego",
            "reference": f"policies/{entry['policy_dir']}/{entry['policy_stem']}.rego",
        },
        "remediation": {
            "template_ref": (f"remediation/{entry['template_dir']}/{entry['template_stem']}.tftpl"),
            "cost_impact_monthly_usd": float(entry.get("cost_impact", 0)),
        },
        "remediates": entry["remediates"],
    }
    if entry.get("alternatives"):
        rule["alternatives"] = list(entry["alternatives"])
    if entry.get("parameters"):
        rule["parameters"] = dict(entry["parameters"])
    rule["provenance"] = {
        "source_url": entry["provenance_url"],
        "resolved_ref": entry.get("resolved_ref", DEFAULT_REF),
        "content_hash": entry.get("content_hash", DEFAULT_HASH),
        "license": entry.get("license", "LicenseRef-reference-only"),
        "redistribution": entry.get("redistribution", "reference-only"),
        "retrieved_at": entry.get("retrieved_at", "2026-07-06T00:00:00Z"),
    }
    if entry.get("source_version"):
        rule["provenance"]["source_version"] = entry["source_version"]
    if entry.get("applies_to"):
        rule["applies_to"] = dict(entry["applies_to"])
    return _yaml_dump(rule)


def _rego_body(entry: dict[str, Any]) -> str:
    header = "\n".join(
        [
            "# METADATA",
            f"# title: {entry['policy_title']}",
            "# description: |",
            *(f"#   {line}" for line in entry["policy_description"].strip().splitlines()),
            "# custom:",
            f"#   rule_id: {entry['id']}",
            f"#   severity: {entry['severity']}",
            f"#   category: {entry['category']}",
        ]
    )
    return "\n".join(
        [
            header,
            f"package {entry['policy_package']}",
            "",
            "import rego.v1",
            "",
            entry["policy_body"].rstrip(),
            "",
        ]
    )


def _tftpl_body(entry: dict[str, Any]) -> str:
    header = "\n".join(
        [
            f"# {entry['remediates']} - Terraform patch template.",
            "#",
            f"# Referenced by rule `{entry['id']}`.",
            f"# {entry['template_summary']}",
        ]
    )
    return f"{header}\n\n{entry['template_body'].rstrip()}\n"


def main() -> int:
    with MANIFEST_PATH.open("r", encoding="utf-8") as fh:
        manifest = yaml.safe_load(fh)
    entries = manifest["rules"]
    written = 0
    for entry in entries:
        rule_path = CATALOG_ROOT / f"{entry['id']}.yaml"
        policy_path = POLICIES_ROOT / entry["policy_dir"] / f"{entry['policy_stem']}.rego"
        template_path = REMEDIATION_ROOT / entry["template_dir"] / f"{entry['template_stem']}.tftpl"
        _write(rule_path, _rule_yaml(entry))
        _write(policy_path, _rego_body(entry))
        _write(template_path, _tftpl_body(entry))
        written += 3
    print(f"seed_p1: wrote {written} files ({len(entries)} rules)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
