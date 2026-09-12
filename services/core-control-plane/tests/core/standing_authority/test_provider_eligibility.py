"""Provider-commit-fence eligibility tests for the inert A3-E contracts.

Covers:
- The shipped adapter registry is empty, so every ActionType is ineligible.
- Every shipped ActionType in ``rule-catalog/action-types`` classifies as
  ``INELIGIBLE_CAPABILITY``, by bare name and by ``name@version``.
- The capability value matches ``LeaseOutcome.INELIGIBLE_CAPABILITY``.
- Derivation is canonical, deduplicated, and fail-closed on malformed input.
- ``build_candidate_record`` exposes no caller-supplied ineligible parameter, and the
  record constructor rejects a hand-declared partition.
- Static proofs: no authority path imports the module, no shipped module assigns to the
  adapter registry, and no shipped module references the test-only hypothetical helper.
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from fdai.core.standing_authority.lease import LeaseOutcome
from fdai.core.standing_authority.lifecycle import LifecycleFence
from fdai.core.standing_authority.lifecycle_codec import AuthorizationLifecycleError
from fdai.core.standing_authority.promotion_candidate import (
    PromotionCandidateRecord,
    build_candidate_record,
)
from fdai.core.standing_authority.provider_eligibility import (
    A3E_COMMIT_FENCE_ADAPTERS,
    ProviderEligibilityPartition,
    ProviderFenceCapability,
    a3e_fence_capability,
    derive_ineligible_provider_action_types,
    partition_provider_eligibility,
)
from tests.core.standing_authority.hypothetical_provider_eligibility import (
    HELPER_MODULE_NAME,
    hypothetical_fence_capable,
)

SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src" / "fdai"
REPO_ROOT = Path(__file__).resolve().parents[5]
ACTION_TYPE_DIR = REPO_ROOT / "rule-catalog" / "action-types"
REGISTRY_NAME = "A3E_COMMIT_FENCE_ADAPTERS"

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
REVISION_ID = "sha256:" + "a" * 64
AUTH_DIGEST = "sha256:" + "f" * 64
EVIDENCE = ("sha256:" + "e" * 64,)
FENCE = LifecycleFence(
    family_id="family:one",
    revision_id=REVISION_ID,
    fencing_generation=3,
    transition_digest="sha256:" + "d" * 64,
)


def _shipped_action_types() -> tuple[tuple[str, str], ...]:
    entries: list[tuple[str, str]] = []
    for path in sorted(ACTION_TYPE_DIR.glob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        entries.append((str(document["name"]), str(document["version"])))
    return tuple(entries)


def _shipped_python_files() -> tuple[Path, ...]:
    return tuple(path for path in SOURCE_ROOT.rglob("*.py") if "__pycache__" not in path.parts)


# ---------------------------------------------------------------------------
# Tests: registry state and classification
# ---------------------------------------------------------------------------


def test_no_provider_adapter_is_registered_as_fence_capable() -> None:
    """Zero adapters validate lease and fencing generation atomically at commit."""
    assert A3E_COMMIT_FENCE_ADAPTERS == frozenset()


def test_every_shipped_action_type_is_provider_ineligible() -> None:
    shipped = _shipped_action_types()
    assert len(shipped) >= 40, "ActionType catalog did not load"
    for name, version in shipped:
        assert a3e_fence_capability(name) is ProviderFenceCapability.INELIGIBLE_CAPABILITY
        assert (
            a3e_fence_capability(f"{name}@{version}")
            is ProviderFenceCapability.INELIGIBLE_CAPABILITY
        )


def test_every_shipped_action_type_partitions_as_ineligible() -> None:
    ids = tuple(f"{name}@{version}" for name, version in _shipped_action_types())
    partition = partition_provider_eligibility(ids)
    assert partition.fence_capable == ()
    assert partition.ineligible == tuple(sorted(set(ids)))


def test_unknown_action_type_is_ineligible() -> None:
    assert (
        a3e_fence_capability("ops.not-a-shipped-action@9.9.9")
        is ProviderFenceCapability.INELIGIBLE_CAPABILITY
    )


def test_capability_value_matches_lease_outcome() -> None:
    """Machine records stay comparable across the lease and eligibility contracts."""
    assert (
        ProviderFenceCapability.INELIGIBLE_CAPABILITY.value
        == LeaseOutcome.INELIGIBLE_CAPABILITY.value
    )


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_action_type_fails_closed(value: str) -> None:
    with pytest.raises(AuthorizationLifecycleError):
        a3e_fence_capability(value)


def test_partition_is_canonical_and_deduplicated() -> None:
    partition = partition_provider_eligibility(("ops.b", "ops.a", "ops.b"))
    assert partition.ineligible == ("ops.a", "ops.b")
    assert partition.fence_capable == ()


def test_partition_rejects_noncanonical_construction() -> None:
    with pytest.raises(AuthorizationLifecycleError):
        ProviderEligibilityPartition(fence_capable=(), ineligible=("ops.b", "ops.a"))


def test_partition_rejects_overlapping_halves() -> None:
    with pytest.raises(AuthorizationLifecycleError):
        ProviderEligibilityPartition(fence_capable=("ops.a",), ineligible=("ops.a",))


def test_derive_returns_every_id_while_the_registry_is_empty() -> None:
    assert derive_ineligible_provider_action_types(("ops.b", "ops.a")) == ("ops.a", "ops.b")


def test_hypothetical_capability_is_scoped_to_the_block() -> None:
    with hypothetical_fence_capable(("ops.a",)):
        assert a3e_fence_capability("ops.a") is ProviderFenceCapability.COMMIT_FENCE_ENFORCED
    assert a3e_fence_capability("ops.a") is ProviderFenceCapability.INELIGIBLE_CAPABILITY


# ---------------------------------------------------------------------------
# Tests: no caller-declared eligibility
# ---------------------------------------------------------------------------


def test_builder_has_no_caller_supplied_ineligible_parameter() -> None:
    parameters = inspect.signature(build_candidate_record).parameters
    assert "ineligible_provider_action_types" not in parameters
    assert "eligible_action_types" in parameters


def test_builder_derives_the_ineligible_set_for_a_shipped_action_type() -> None:
    record = build_candidate_record(
        family_id="family:one",
        revision_id=REVISION_ID,
        fence=FENCE,
        eligible_action_types=("ops.start-vm@1.0.0",),
        evidence_requirements=EVIDENCE,
        source_revision_id="source:v1",
        creator_principal="human:creator",
        authentication_evidence_digest=AUTH_DIGEST,
        created_at=NOW,
        required_reviewer_principals=("human:reviewer-a", "human:reviewer-b"),
        quorum_required=2,
    )
    assert record.ineligible_provider_action_types == ("ops.start-vm@1.0.0",)


def test_record_constructor_rejects_a_hand_declared_partition() -> None:
    """The direct dataclass path cannot bypass derivation either."""
    with hypothetical_fence_capable(("ops.a",)):
        record = build_candidate_record(
            family_id="family:one",
            revision_id=REVISION_ID,
            fence=FENCE,
            eligible_action_types=("ops.a",),
            evidence_requirements=EVIDENCE,
            source_revision_id="source:v1",
            creator_principal="human:creator",
            authentication_evidence_digest=AUTH_DIGEST,
            created_at=NOW,
            required_reviewer_principals=("human:reviewer-a", "human:reviewer-b"),
            quorum_required=2,
        )
        assert record.ineligible_provider_action_types == ()
    fields = {
        "candidate_id": record.candidate_id,
        "family_id": record.family_id,
        "revision_id": record.revision_id,
        "fence": record.fence,
        "lease_contract_version": record.lease_contract_version,
        "eligible_action_types": record.eligible_action_types,
        "ineligible_provider_action_types": (),
        "evidence_requirements": record.evidence_requirements,
        "source_revision_id": record.source_revision_id,
        "creator_principal": record.creator_principal,
        "authentication_evidence_digest": record.authentication_evidence_digest,
        "created_at": record.created_at,
        "required_reviewer_principals": record.required_reviewer_principals,
        "quorum_required": record.quorum_required,
    }
    with pytest.raises(AuthorizationLifecycleError, match="derived"):
        PromotionCandidateRecord(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Static non-import and non-mutation proofs
# ---------------------------------------------------------------------------


def test_provider_eligibility_not_imported_by_authority_paths() -> None:
    """Agents, risk_gate, executor, hil_resume, workflow, control_loop, and
    composition must not import the eligibility module, by submodule path or by
    package re-export."""
    forbidden_prefix = "fdai.core.standing_authority.provider_eligibility"
    forbidden_symbols = frozenset(
        {
            "A3E_COMMIT_FENCE_ADAPTERS",
            "ProviderEligibilityPartition",
            "ProviderFenceCapability",
            "a3e_fence_capability",
            "derive_ineligible_provider_action_types",
            "partition_provider_eligibility",
            "provider_eligibility",
        }
    )
    roots = (
        "agents",
        "core/risk_gate",
        "core/executor",
        "core/hil_resume",
        "core/workflow",
        "core/control_loop",
        "composition",
    )
    violations: list[str] = []
    for root in roots:
        path = SOURCE_ROOT / root
        assert path.exists(), f"authority path is missing from scan root: {root}"
        files = (path,) if path.is_file() else path.rglob("*.py")
        for candidate_file in files:
            tree = ast.parse(candidate_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                modules: tuple[str, ...] = ()
                if isinstance(node, ast.Import):
                    modules = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    # `from fdai.core.standing_authority import a3e_fence_capability`
                    # reaches the same code through the package re-export, so the
                    # imported names must be scanned too, not only node.module.
                    modules = (node.module,) + tuple(
                        f"{node.module}.{alias.name}" for alias in node.names
                    )
                    if node.module.startswith("fdai.core.standing_authority") and any(
                        alias.name in forbidden_symbols for alias in node.names
                    ):
                        violations.append(str(candidate_file.relative_to(SOURCE_ROOT)))
                if any(m.startswith(forbidden_prefix) for m in modules):
                    violations.append(str(candidate_file.relative_to(SOURCE_ROOT)))
    assert violations == [], f"provider_eligibility imported from authority paths: {violations}"


def test_no_shipped_module_mutates_the_adapter_registry() -> None:
    """Only the eligibility module may bind the registry name, and never at runtime."""
    owner = SOURCE_ROOT / "core" / "standing_authority" / "provider_eligibility.py"
    violations: list[str] = []
    for path in _shipped_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            for target in targets:
                named = isinstance(target, ast.Name) and target.id == REGISTRY_NAME
                attributed = isinstance(target, ast.Attribute) and target.attr == REGISTRY_NAME
                if (named and path != owner) or attributed:
                    violations.append(str(path.relative_to(SOURCE_ROOT)))
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "setattr"
                and any(
                    isinstance(arg, ast.Constant) and arg.value == REGISTRY_NAME
                    for arg in node.args
                )
            ):
                violations.append(str(path.relative_to(SOURCE_ROOT)))
    assert violations == [], f"shipped modules mutate {REGISTRY_NAME}: {violations}"


def test_no_shipped_module_references_the_hypothetical_helper() -> None:
    violations = [
        str(path.relative_to(SOURCE_ROOT))
        for path in _shipped_python_files()
        if HELPER_MODULE_NAME in path.read_text(encoding="utf-8")
    ]
    assert violations == [], f"shipped modules reference the test helper: {violations}"
