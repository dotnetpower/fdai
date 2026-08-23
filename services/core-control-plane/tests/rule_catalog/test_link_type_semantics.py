"""LinkType role and composable semantic-trait contract tests."""

from __future__ import annotations

import pytest
from fdai.rule_catalog.schema.ontology_provenance import ontology_content_hash
from fdai.shared.contracts.models import LinkCardinality, OntologyLinkType


def test_link_type_accepts_paired_roles_and_composable_traits() -> None:
    link = OntologyLinkType(
        schema_version="1.0.0",
        name="routes_to",
        version="1.1.0",
        from_type="Resource",
        to_type="Resource",
        cardinality=LinkCardinality.MANY_TO_ONE,
        forward_role="routes_to",
        reverse_role="receives_route_from",
        semantic_traits=("connectivity", "traffic"),
    )

    assert link.forward_role == "routes_to"
    assert tuple(item.value for item in link.semantic_traits) == ("connectivity", "traffic")


def test_link_type_rejects_one_sided_roles() -> None:
    with pytest.raises(ValueError, match="roles MUST be declared together"):
        OntologyLinkType(
            schema_version="1.0.0",
            name="contains",
            version="2.1.0",
            from_type="Resource",
            to_type="Resource",
            cardinality=LinkCardinality.ONE_TO_MANY,
            forward_role="contains",
        )


def test_link_type_rejects_duplicate_semantic_traits() -> None:
    with pytest.raises(ValueError, match="semantic_traits MUST be unique"):
        OntologyLinkType(
            schema_version="1.0.0",
            name="depends_on",
            version="1.1.0",
            from_type="Resource",
            to_type="Resource",
            cardinality=LinkCardinality.MANY_TO_MANY,
            semantic_traits=("dependency", "dependency"),
        )


def test_legacy_link_hash_omits_only_absent_additive_semantics() -> None:
    legacy = OntologyLinkType(
        schema_version="1.0.0",
        name="depends_on",
        version="1.0.0",
        from_type="Resource",
        to_type="Resource",
        cardinality=LinkCardinality.MANY_TO_MANY,
    )
    explicit = OntologyLinkType(
        schema_version="1.0.0",
        name="depends_on",
        version="1.1.0",
        from_type="Resource",
        to_type="Resource",
        cardinality=LinkCardinality.MANY_TO_MANY,
        forward_role="depends_on",
        reverse_role="required_by",
        semantic_traits=("dependency",),
    )

    assert ontology_content_hash(legacy) != ontology_content_hash(explicit)
