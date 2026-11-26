"""OPA AST semantic identity tests for authored Rego policies."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fdai.rule_catalog.schema import rego_semantics
from fdai.rule_catalog.schema.bounded_process import BoundedProcessResult
from fdai.rule_catalog.schema.rego_semantics import load_rego_semantics

REPO_ROOT = Path(__file__).resolve().parents[4]
POLICY = REPO_ROOT / "policies" / "object_storage" / "public_access.rego"
requires_opa = pytest.mark.skipif(shutil.which("opa") is None, reason="opa binary unavailable")


@requires_opa
def test_normalized_semantic_digest_ignores_comments_and_whitespace(tmp_path: Path) -> None:
    original = POLICY.read_text(encoding="utf-8")
    variant = original.replace(
        "import rego.v1\n",
        "import rego.v1\n\n# Formatting-only review note.\n",
    ).replace("\tinput.resource.type", "    input.resource.type")
    variant_path = tmp_path / "public_access.rego"
    variant_path.write_text(variant, encoding="utf-8")

    original_semantics = load_rego_semantics(POLICY)
    variant_semantics = load_rego_semantics(variant_path)

    assert original_semantics.content_digest != variant_semantics.content_digest
    assert (
        original_semantics.normalized_semantic_digest
        == variant_semantics.normalized_semantic_digest
    )


@requires_opa
def test_normalized_semantic_digest_changes_with_predicate(tmp_path: Path) -> None:
    original = POLICY.read_text(encoding="utf-8")
    changed = original.replace('public_access == "enabled"', 'public_access == "disabled"')
    changed_path = tmp_path / "public_access.rego"
    changed_path.write_text(changed, encoding="utf-8")

    original_semantics = load_rego_semantics(POLICY)
    changed_semantics = load_rego_semantics(changed_path)

    assert (
        original_semantics.normalized_semantic_digest
        != changed_semantics.normalized_semantic_digest
    )


def test_source_built_opa_formatted_source_falls_back_to_parse_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = """# METADATA
# title: Test policy
# description: Test source-built OPA output.
# custom:
#   rule_id: test.policy
#   severity: high
#   category: security
package fdai.test

import rego.v1

deny if {
    input.resource.props.enabled == true
}
"""
    path = tmp_path / "policy.rego"
    path.write_text(source, encoding="utf-8")
    ast = {
        "package": {
            "path": [
                {"type": "var", "value": "data"},
                {"type": "string", "value": "fdai"},
                {"type": "string", "value": "test"},
            ]
        },
        "rules": [
            {
                "head": {"name": "deny"},
                "body": [
                    {
                        "type": "ref",
                        "value": [
                            {"type": "var", "value": "input"},
                            {"type": "string", "value": "resource"},
                            {"type": "string", "value": "props"},
                            {"type": "string", "value": "enabled"},
                        ],
                    }
                ],
            }
        ],
    }
    results = iter(
        (
            BoundedProcessResult(returncode=0, stdout=json.dumps(source).encode()),
            BoundedProcessResult(
                returncode=0,
                stdout=json.dumps({"result": [{"expressions": [{"value": ast}]}]}).encode(),
            ),
        )
    )
    calls: list[tuple[list[str], bytes | None]] = []

    def run(command, **kwargs):
        calls.append((list(command), kwargs.get("input_data")))
        return next(results)

    monkeypatch.setattr(rego_semantics, "run_bounded_process", run)

    semantics = load_rego_semantics(path, opa_binary="/usr/local/bin/opa")

    assert semantics.package == "fdai.test"
    assert semantics.decision_path == "data.fdai.test.deny"
    assert semantics.rule_id == "test.policy"
    assert semantics.property_paths == ("enabled",)
    assert calls[0][0][1:3] == ["parse", "--format=json"]
    assert calls[1][0][1:4] == ["eval", "--stdin-input", "--format=json"]
    assert json.loads(calls[1][1] or b"null") == source
