from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from fdai.core.ontology_platform import (
    InterpretationCandidateSource,
    SemanticOperationClass,
    VerifiedInterpretationBasis,
    build_semantic_candidate,
    verify_semantic_candidate,
)
from fdai.shared.contracts.models import (
    OntologyDeclarationKind,
    OntologyDeclarationRef,
    OntologyRelease,
)

_DIGEST_A = "sha256:" + "a" * 64
_DIGEST_B = "sha256:" + "b" * 64
_DIGEST_C = "sha256:" + "c" * 64


@dataclass(frozen=True, slots=True)
class CatalogAuthority:
    digest: str
    candidate_digests: frozenset[str] = frozenset()

    def contains(self, candidate: Any) -> bool:
        return candidate.candidate_digest in self.candidate_digests


def _catalog(*candidates: Any, digest: str = _DIGEST_B) -> CatalogAuthority:
    return CatalogAuthority(
        digest=digest,
        candidate_digests=frozenset(candidate.candidate_digest for candidate in candidates),
    )


def _release() -> OntologyRelease:
    return OntologyRelease(
        digest=_DIGEST_A,
        declarations=(
            OntologyDeclarationRef(
                kind=OntologyDeclarationKind.FUNCTION,
                name="inventory.select_resources",
                version="1.0.0",
                declaration_digest=_DIGEST_B,
            ),
            OntologyDeclarationRef(
                kind=OntologyDeclarationKind.ACTION,
                name="ops.start-vm",
                version="1.0.0",
                declaration_digest=_DIGEST_C,
            ),
        ),
    )


def test_embedding_candidate_is_explicitly_non_authoritative() -> None:
    release = _release()

    candidate = build_semantic_candidate(
        source=InterpretationCandidateSource.EMBEDDING,
        operation_class=SemanticOperationClass.QUERY,
        target_ref=release.type_ref(
            OntologyDeclarationKind.FUNCTION,
            "inventory.select_resources",
        ),
        arguments={"resource_type": "compute.vm", "state": "running"},
        semantic_catalog_digest=_DIGEST_B,
        input_text="show active VMs",
        score=0.96,
        unresolved_terms=(),
    )

    assert candidate.authority == "candidate_only"
    assert candidate.candidate_digest.startswith("sha256:")


def test_unresolved_candidate_cannot_be_verified() -> None:
    release = _release()
    candidate = build_semantic_candidate(
        source=InterpretationCandidateSource.MODEL,
        operation_class=SemanticOperationClass.QUERY,
        target_ref=release.type_ref(
            OntologyDeclarationKind.FUNCTION,
            "inventory.select_resources",
        ),
        arguments={"resource_type": "compute.vm"},
        semantic_catalog_digest=_DIGEST_B,
        input_text="started VMs",
        score=None,
        unresolved_terms=("started",),
    )

    with pytest.raises(ValueError, match="unresolved"):
        verify_semantic_candidate(
            candidate,
            release=release,
            active_semantic_catalog=_catalog(),
            basis=VerifiedInterpretationBasis.OPERATOR_CONFIRMATION,
            basis_ref="conversation-turn:confirmation-1",
            basis_validator=lambda *_args: True,
        )


def test_verified_plan_is_replay_stable_for_canonical_arguments() -> None:
    release = _release()
    target = release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        "inventory.select_resources",
    )
    left = build_semantic_candidate(
        source=InterpretationCandidateSource.LEXICAL,
        operation_class=SemanticOperationClass.QUERY,
        target_ref=target,
        arguments={"state": "running", "resource_type": "compute.vm"},
        semantic_catalog_digest=_DIGEST_B,
        input_text="running VMs",
        score=1.0,
        unresolved_terms=(),
    )
    right = build_semantic_candidate(
        source=InterpretationCandidateSource.LEXICAL,
        operation_class=SemanticOperationClass.QUERY,
        target_ref=target,
        arguments={"resource_type": "compute.vm", "state": "running"},
        semantic_catalog_digest=_DIGEST_B,
        input_text="running VMs",
        score=1.0,
        unresolved_terms=(),
    )

    left_plan = verify_semantic_candidate(
        left,
        release=release,
        active_semantic_catalog=_catalog(left),
        basis=VerifiedInterpretationBasis.EXACT_CATALOG,
        basis_ref=f"catalog:{_DIGEST_B}",
    )
    right_plan = verify_semantic_candidate(
        right,
        release=release,
        active_semantic_catalog=_catalog(right),
        basis=VerifiedInterpretationBasis.EXACT_CATALOG,
        basis_ref=f"catalog:{_DIGEST_B}",
    )

    assert left_plan.plan_digest == right_plan.plan_digest
    assert left_plan.execution_authority is False


def test_query_cannot_target_action_type() -> None:
    release = _release()
    candidate = build_semantic_candidate(
        source=InterpretationCandidateSource.MODEL,
        operation_class=SemanticOperationClass.QUERY,
        target_ref=release.type_ref(OntologyDeclarationKind.ACTION, "ops.start-vm"),
        arguments={"resource": "vm-example"},
        semantic_catalog_digest=_DIGEST_B,
        input_text="start the VM",
        score=None,
        unresolved_terms=(),
    )

    with pytest.raises(ValueError, match="query.*function"):
        verify_semantic_candidate(
            candidate,
            release=release,
            active_semantic_catalog=_catalog(),
            basis=VerifiedInterpretationBasis.OPERATOR_CONFIRMATION,
            basis_ref="conversation-turn:confirmation-2",
            basis_validator=lambda *_args: True,
        )


def test_action_interpretation_remains_proposal_only() -> None:
    release = _release()
    candidate = build_semantic_candidate(
        source=InterpretationCandidateSource.MODEL,
        operation_class=SemanticOperationClass.ACTION_DRAFT,
        target_ref=release.type_ref(OntologyDeclarationKind.ACTION, "ops.start-vm"),
        arguments={"resource": "vm-example"},
        semantic_catalog_digest=_DIGEST_B,
        input_text="start the VM",
        score=None,
        unresolved_terms=(),
    )

    plan = verify_semantic_candidate(
        candidate,
        release=release,
        active_semantic_catalog=_catalog(),
        basis=VerifiedInterpretationBasis.OPERATOR_CONFIRMATION,
        basis_ref="conversation-turn:confirmation-3",
        basis_validator=lambda *_args: True,
    )

    assert plan.operation_class is SemanticOperationClass.ACTION_DRAFT
    assert plan.execution_authority is False


def test_stale_release_cannot_verify_candidate() -> None:
    release = _release()
    candidate = build_semantic_candidate(
        source=InterpretationCandidateSource.LEXICAL,
        operation_class=SemanticOperationClass.QUERY,
        target_ref=release.type_ref(
            OntologyDeclarationKind.FUNCTION,
            "inventory.select_resources",
        ),
        arguments={"resource_type": "compute.vm"},
        semantic_catalog_digest=_DIGEST_B,
        input_text="VM list",
        score=1.0,
        unresolved_terms=(),
    )
    stale_release = OntologyRelease(digest=_DIGEST_C, declarations=release.declarations)

    with pytest.raises(ValueError, match="release"):
        verify_semantic_candidate(
            candidate,
            release=stale_release,
            active_semantic_catalog=_catalog(candidate),
            basis=VerifiedInterpretationBasis.EXACT_CATALOG,
            basis_ref=f"catalog:{_DIGEST_B}",
        )


def test_candidate_arguments_are_defensive_and_digest_bound() -> None:
    release = _release()
    candidate = build_semantic_candidate(
        source=InterpretationCandidateSource.LEXICAL,
        operation_class=SemanticOperationClass.QUERY,
        target_ref=release.type_ref(
            OntologyDeclarationKind.FUNCTION,
            "inventory.select_resources",
        ),
        arguments={"filter": {"state": ["running"]}},
        semantic_catalog_digest=_DIGEST_B,
        input_text="running VMs",
        score=1.0,
        unresolved_terms=(),
    )

    projected = candidate.arguments
    projected["filter"]["state"].append("stopped")

    assert candidate.arguments == {"filter": {"state": ["running"]}}
    plan = verify_semantic_candidate(
        candidate,
        release=release,
        active_semantic_catalog=_catalog(candidate),
        basis=VerifiedInterpretationBasis.EXACT_CATALOG,
        basis_ref=f"catalog:{_DIGEST_B}",
    )
    assert plan.arguments == {"filter": {"state": ["running"]}}


def test_non_catalog_basis_requires_external_evidence_validation() -> None:
    release = _release()
    candidate = build_semantic_candidate(
        source=InterpretationCandidateSource.MODEL,
        operation_class=SemanticOperationClass.ACTION_DRAFT,
        target_ref=release.type_ref(OntologyDeclarationKind.ACTION, "ops.start-vm"),
        arguments={"resource": "vm-example"},
        semantic_catalog_digest=_DIGEST_B,
        input_text="start the VM",
        score=None,
        unresolved_terms=(),
    )

    with pytest.raises(ValueError, match="basis evidence"):
        verify_semantic_candidate(
            candidate,
            release=release,
            active_semantic_catalog=_catalog(),
            basis=VerifiedInterpretationBasis.OPERATOR_CONFIRMATION,
            basis_ref="conversation-turn:confirmation-4",
        )
    with pytest.raises(ValueError, match="basis evidence"):
        verify_semantic_candidate(
            candidate,
            release=release,
            active_semantic_catalog=_catalog(),
            basis=VerifiedInterpretationBasis.OPERATOR_CONFIRMATION,
            basis_ref="conversation-turn:confirmation-4",
            basis_validator=lambda *_args: False,
        )


def test_foreign_semantic_catalog_cannot_verify_candidate() -> None:
    release = _release()
    candidate = build_semantic_candidate(
        source=InterpretationCandidateSource.LEXICAL,
        operation_class=SemanticOperationClass.QUERY,
        target_ref=release.type_ref(
            OntologyDeclarationKind.FUNCTION,
            "inventory.select_resources",
        ),
        arguments={"resource_type": "compute.vm"},
        semantic_catalog_digest=_DIGEST_B,
        input_text="VM list",
        score=1.0,
        unresolved_terms=(),
    )

    with pytest.raises(ValueError, match="stale semantic catalog"):
        verify_semantic_candidate(
            candidate,
            release=release,
            active_semantic_catalog=_catalog(digest=_DIGEST_C),
            basis=VerifiedInterpretationBasis.EXACT_CATALOG,
            basis_ref=f"catalog:{_DIGEST_B}",
        )


def test_exact_catalog_candidate_must_exist_in_active_catalog() -> None:
    release = _release()
    candidate = build_semantic_candidate(
        source=InterpretationCandidateSource.LEXICAL,
        operation_class=SemanticOperationClass.QUERY,
        target_ref=release.type_ref(
            OntologyDeclarationKind.FUNCTION,
            "inventory.select_resources",
        ),
        arguments={"resource_type": "compute.vm"},
        semantic_catalog_digest=_DIGEST_B,
        input_text="VM list",
        score=1.0,
        unresolved_terms=(),
    )

    with pytest.raises(ValueError, match="absent from the active catalog"):
        verify_semantic_candidate(
            candidate,
            release=release,
            active_semantic_catalog=_catalog(),
            basis=VerifiedInterpretationBasis.EXACT_CATALOG,
            basis_ref=f"catalog:{_DIGEST_B}",
        )
