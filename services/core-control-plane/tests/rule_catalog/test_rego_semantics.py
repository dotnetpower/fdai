"""OPA AST semantic identity tests for authored Rego policies."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
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
