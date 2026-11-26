from __future__ import annotations

from pathlib import Path

from fdai.delivery.rule_revision_registry import CatalogRuleRevisionRegistry
from fdai_service_contracts.rule_activation_manifest import RuleRevisionIdentityRef

REPO_ROOT = Path(__file__).resolve().parents[4]


def test_catalog_registry_requires_exact_retained_revision_closure() -> None:
    registry = CatalogRuleRevisionRegistry(REPO_ROOT)
    revision = RuleRevisionIdentityRef(
        rule_id="cache.zone-redundant",
        rule_version="1.0.0",
        revision_digest=("sha256:cb269f00d1f0362c18b89326f1579171edd60fc1bcfd42313893294d4fb07af9"),
    )

    assert registry.has_retained_closure(revision)
    assert not registry.has_retained_closure(
        revision.model_copy(update={"revision_digest": "sha256:" + ("0" * 64)})
    )
