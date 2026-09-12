"""Tests for the inert A3-E shadow-reversion command, writer seam, and orchestration.

Covers:
- Content-addressed command identity and every required binding.
- Rejection of matched/pending evidence, non-reversion transitions, and NONE plans.
- Actor/reviewer separation, agent and executor identity rejection.
- Stable idempotency across proposers, distinct per revision/plan/fence.
- Two-phase audit: intent digest precedes mutation; terminal digest covers it.
- Fail-closed orchestration on unrecorded intent, stale fence, writer failure,
  duplicate application, and unrecorded terminal audit.
- Static proofs: no authority, runtime, or delivery path imports the module, no
  shipped writer implementation exists, and the module never reaches the
  authoritative ActionPromotionRegistry.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.standing_authority.effect_shadow_reversion import (
    EffectEvidenceDisposition,
    ShadowReversionPlan,
    ShadowReversionTransition,
)
from fdai.core.standing_authority.lifecycle import LifecycleFence
from fdai.core.standing_authority.lifecycle_codec import AuthorizationLifecycleError
from fdai.core.standing_authority.shadow_reversion_command import (
    REVERTIBLE_DISPOSITIONS,
    SHADOW_REVERSION_CONTRACT_VERSION,
    ExpectedAuthorizationState,
    ShadowReversionCommand,
    ShadowReversionIntent,
    ShadowReversionOutcome,
    ShadowReversionSafetyBindings,
    ShadowReversionTerminal,
    ShadowReversionWriter,
    apply_shadow_reversion,
    build_shadow_reversion_command,
)
from tests.core.standing_authority.inertness_scan import (
    find_inertness_violations,
    find_text_references,
    shipped_modules,
)

SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src" / "fdai"
MODULE_PATH = SOURCE_ROOT / "core" / "standing_authority" / "shadow_reversion_command.py"

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
REVISION = "a" * 40
FINDING_ID = "sha256:" + "1" * 64
PLAN_ID = "sha256:" + "2" * 64
AUTH_DIGEST = "sha256:" + "f" * 64
PROPOSER = "human:proposer"
REVIEWER = "human:reviewer"
ACTION_TYPES = ("ops.start-vm@1.0.0",)

FENCE = LifecycleFence(
    family_id="family:one",
    revision_id="sha256:" + "b" * 64,
    fencing_generation=4,
    transition_digest="sha256:" + "d" * 64,
)
OTHER_FENCE = LifecycleFence(
    family_id="family:one",
    revision_id="sha256:" + "b" * 64,
    fencing_generation=5,
    transition_digest="sha256:" + "e" * 64,
)

SAFETY = ShadowReversionSafetyBindings(
    stop_condition_ref="stop:provider_api_error_streak",
    rollback_plan_ref="rollback:ops.deallocate-vm",
    kill_switch_ref="killswitch:system/kill-switch",
    blast_radius_scope="resource",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _command(**overrides: object) -> ShadowReversionCommand:
    kwargs: dict[str, object] = dict(
        source_revision_id=REVISION,
        reverted_action_types=ACTION_TYPES,
        finding_id=FINDING_ID,
        plan_id=PLAN_ID,
        disposition=EffectEvidenceDisposition.FAILED,
        required_transition=ShadowReversionTransition.RETURN_TO_SHADOW,
        reason_code="effects_mismatched",
        expected_authorization=FENCE,
        expected_authorization_state=ExpectedAuthorizationState.ACTIVE,
        safety=SAFETY,
        proposer_principal=PROPOSER,
        reviewer_principal=REVIEWER,
        authentication_evidence_digest=AUTH_DIGEST,
        proposed_at=NOW,
    )
    kwargs.update(overrides)
    return ShadowReversionCommand(**kwargs)  # type: ignore[arg-type]


class _Writer:
    """Test-only writer double. No shipped adapter implements the Protocol."""

    def __init__(
        self,
        *,
        intent_ok: bool = True,
        fence_ok: bool = True,
        applied: bool = True,
        terminal_ok: bool = True,
        apply_error: Exception | None = None,
        terminal_error: Exception | None = None,
    ) -> None:
        self.intent_ok = intent_ok
        self.fence_ok = fence_ok
        self.applied = applied
        self.terminal_ok = terminal_ok
        self.apply_error = apply_error
        self.terminal_error = terminal_error
        self.calls: list[str] = []
        self.applied_keys: list[str] = []

    async def record_intent(self, intent: ShadowReversionIntent) -> bool:
        self.calls.append("record_intent")
        return self.intent_ok

    async def current_fence_matches(self, fence: LifecycleFence) -> bool:
        self.calls.append("current_fence_matches")
        return self.fence_ok

    async def apply(
        self,
        command: ShadowReversionCommand,
        intent: ShadowReversionIntent,
    ) -> bool:
        self.calls.append("apply")
        if self.apply_error is not None:
            raise self.apply_error
        self.applied_keys.append(command.idempotency_key)
        return self.applied

    async def record_terminal(self, terminal: ShadowReversionTerminal) -> bool:
        self.calls.append("record_terminal")
        if self.terminal_error is not None:
            raise self.terminal_error
        return self.terminal_ok


# ---------------------------------------------------------------------------
# Tests: bindings and identity
# ---------------------------------------------------------------------------


def test_command_binds_every_required_field() -> None:
    command = _command()
    assert command.contract_version == SHADOW_REVERSION_CONTRACT_VERSION
    assert command.source_revision_id == REVISION
    assert command.reverted_action_types == ACTION_TYPES
    assert command.finding_id == FINDING_ID
    assert command.plan_id == PLAN_ID
    assert command.expected_authorization == FENCE
    assert command.expected_authorization_state is ExpectedAuthorizationState.ACTIVE
    assert command.safety.kill_switch_ref == "killswitch:system/kill-switch"
    assert command.safety.stop_condition_ref.startswith("stop:")
    assert command.safety.rollback_plan_ref.startswith("rollback:")
    assert command.command_id.startswith("sha256:")
    assert command.idempotency_key.startswith("sha256:")


def test_command_carries_no_authority() -> None:
    command = _command()
    assert command.execution_authority is False
    assert command.promotion_authority is False
    assert command.registry_mutated is False
    assert command.recovery_authority is False
    body = command.audit_body()
    assert body["execution_authority"] is False
    assert body["promotion_authority"] is False
    assert body["registry_mutated"] is False


def test_command_id_is_stable_and_content_addressed() -> None:
    assert _command().command_id == _command().command_id
    assert _command().command_id != _command(reason_code="observation_missing").command_id


def test_command_id_changes_with_fence_generation() -> None:
    assert _command().command_id != _command(expected_authorization=OTHER_FENCE).command_id


@pytest.mark.parametrize(
    "disposition",
    sorted(REVERTIBLE_DISPOSITIONS, key=lambda item: item.value),
)
def test_every_failed_or_unknown_disposition_is_revertible(
    disposition: EffectEvidenceDisposition,
) -> None:
    assert _command(disposition=disposition).disposition is disposition


@pytest.mark.parametrize(
    "disposition",
    [EffectEvidenceDisposition.MATCHED, EffectEvidenceDisposition.PENDING],
)
def test_matched_or_pending_evidence_cannot_justify_reversion(
    disposition: EffectEvidenceDisposition,
) -> None:
    with pytest.raises(AuthorizationLifecycleError, match="failed or unknown"):
        _command(disposition=disposition)


def test_none_transition_is_rejected() -> None:
    with pytest.raises(AuthorizationLifecycleError, match="RETURN_TO_SHADOW"):
        _command(required_transition=ShadowReversionTransition.NONE)


def test_short_revision_is_rejected() -> None:
    with pytest.raises(AuthorizationLifecycleError, match="source_revision_id"):
        _command(source_revision_id="abc123")


def test_empty_action_types_rejected() -> None:
    with pytest.raises(AuthorizationLifecycleError, match="non-empty"):
        _command(reverted_action_types=())


def test_noncanonical_action_types_rejected() -> None:
    with pytest.raises(AuthorizationLifecycleError, match="canonical order"):
        _command(reverted_action_types=("ops.start-vm@1.0.0", "ops.restart-service@1.0.0"))


def test_duplicate_action_types_rejected() -> None:
    with pytest.raises(AuthorizationLifecycleError, match="distinct values"):
        _command(reverted_action_types=("ops.start-vm@1.0.0", "ops.start-vm@1.0.0"))


def test_unversioned_action_type_rejected() -> None:
    with pytest.raises(AuthorizationLifecycleError, match="canonical name@"):
        _command(reverted_action_types=("ops.start-vm",))


# ---------------------------------------------------------------------------
# Tests: identity separation
# ---------------------------------------------------------------------------


def test_self_proposed_review_is_rejected() -> None:
    with pytest.raises(AuthorizationLifecycleError, match="distinct human"):
        _command(reviewer_principal=PROPOSER)


@pytest.mark.parametrize("principal", ["agent:vidar", "identity:thor", "service:bot"])
def test_non_human_principals_are_rejected(principal: str) -> None:
    with pytest.raises(AuthorizationLifecycleError, match="human"):
        _command(proposer_principal=principal)
    with pytest.raises(AuthorizationLifecycleError, match="human"):
        _command(reviewer_principal=principal)


# ---------------------------------------------------------------------------
# Tests: safety bindings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    ["stop_condition_ref", "rollback_plan_ref", "kill_switch_ref"],
)
def test_safety_bindings_require_canonical_refs(field: str) -> None:
    kwargs = {
        "stop_condition_ref": "stop:x",
        "rollback_plan_ref": "rollback:y",
        "kill_switch_ref": "killswitch:z",
        "blast_radius_scope": "resource",
    }
    kwargs[field] = "not a ref"
    with pytest.raises(AuthorizationLifecycleError, match=field):
        ShadowReversionSafetyBindings(**kwargs)  # type: ignore[arg-type]


def test_safety_bindings_require_tested_rollback() -> None:
    with pytest.raises(AuthorizationLifecycleError, match="tested rollback"):
        ShadowReversionSafetyBindings(
            stop_condition_ref="stop:x",
            rollback_plan_ref="rollback:y",
            kill_switch_ref="killswitch:z",
            blast_radius_scope="resource",
            rollback_tested=False,  # type: ignore[arg-type]
        )


def test_safety_bindings_require_bounded_blast_radius() -> None:
    with pytest.raises(AuthorizationLifecycleError, match="blast_radius_scope"):
        ShadowReversionSafetyBindings(
            stop_condition_ref="stop:x",
            rollback_plan_ref="rollback:y",
            kill_switch_ref="killswitch:z",
            blast_radius_scope="subscription",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Tests: idempotency
# ---------------------------------------------------------------------------


def test_idempotency_key_is_stable_across_proposers_and_times() -> None:
    left = _command()
    right = _command(
        proposer_principal="human:other-proposer",
        reviewer_principal="human:other-reviewer",
        proposed_at=NOW + timedelta(hours=3),
    )
    assert left.idempotency_key == right.idempotency_key
    assert left.command_id != right.command_id


def test_idempotency_key_differs_by_revision_plan_and_fence() -> None:
    base = _command().idempotency_key
    assert _command(source_revision_id="c" * 40).idempotency_key != base
    assert _command(plan_id="sha256:" + "3" * 64).idempotency_key != base
    assert _command(expected_authorization=OTHER_FENCE).idempotency_key != base


# ---------------------------------------------------------------------------
# Tests: two-phase audit
# ---------------------------------------------------------------------------


def test_intent_digest_is_content_addressed() -> None:
    command = _command()
    intent = ShadowReversionIntent(
        command_id=command.command_id,
        idempotency_key=command.idempotency_key,
        expected_authorization=FENCE,
        recorded_at=NOW,
    )
    assert intent.intent_digest.startswith("sha256:")
    assert intent.intent_digest != command.command_id


def test_terminal_digest_covers_the_intent_digest() -> None:
    command = _command()
    intent = ShadowReversionIntent(
        command_id=command.command_id,
        idempotency_key=command.idempotency_key,
        expected_authorization=FENCE,
        recorded_at=NOW,
    )
    left = ShadowReversionTerminal(
        command_id=command.command_id,
        idempotency_key=command.idempotency_key,
        intent_digest=intent.intent_digest,
        outcome=ShadowReversionOutcome.APPLIED,
        detail="reversion applied",
        recorded_at=NOW,
    )
    right = ShadowReversionTerminal(
        command_id=command.command_id,
        idempotency_key=command.idempotency_key,
        intent_digest="sha256:" + "9" * 64,
        outcome=ShadowReversionOutcome.APPLIED,
        detail="reversion applied",
        recorded_at=NOW,
    )
    assert left.terminal_audit_digest != right.terminal_audit_digest
    assert left.execution_authority is False
    assert left.promotion_authority is False


# ---------------------------------------------------------------------------
# Tests: builder
# ---------------------------------------------------------------------------


def _plan(
    transition: ShadowReversionTransition = ShadowReversionTransition.RETURN_TO_SHADOW,
    disposition: EffectEvidenceDisposition = EffectEvidenceDisposition.FAILED,
) -> ShadowReversionPlan:
    return ShadowReversionPlan(
        finding_id=FINDING_ID,
        disposition=disposition,
        required_transition=transition,
        reason_code="effects_mismatched",
    )


def test_builder_derives_identity_from_the_plan() -> None:
    plan = _plan()
    command = build_shadow_reversion_command(
        plan=plan,
        source_revision_id=REVISION,
        reverted_action_types=("ops.start-vm@1.0.0", "ops.start-vm@1.0.0"),
        expected_authorization=FENCE,
        expected_authorization_state=ExpectedAuthorizationState.ACTIVE,
        safety=SAFETY,
        proposer_principal=PROPOSER,
        reviewer_principal=REVIEWER,
        authentication_evidence_digest=AUTH_DIGEST,
        proposed_at=NOW,
    )
    assert command.finding_id == plan.finding_id
    assert command.plan_id == plan.plan_id
    assert command.disposition is plan.disposition
    assert command.reverted_action_types == ("ops.start-vm@1.0.0",)


def test_builder_refuses_a_none_transition_plan() -> None:
    plan = _plan(
        transition=ShadowReversionTransition.NONE,
        disposition=EffectEvidenceDisposition.MATCHED,
    )
    with pytest.raises(AuthorizationLifecycleError, match="RETURN_TO_SHADOW"):
        build_shadow_reversion_command(
            plan=plan,
            source_revision_id=REVISION,
            reverted_action_types=ACTION_TYPES,
            expected_authorization=FENCE,
            expected_authorization_state=ExpectedAuthorizationState.ACTIVE,
            safety=SAFETY,
            proposer_principal=PROPOSER,
            reviewer_principal=REVIEWER,
            authentication_evidence_digest=AUTH_DIGEST,
            proposed_at=NOW,
        )


# ---------------------------------------------------------------------------
# Tests: fail-closed orchestration
# ---------------------------------------------------------------------------


async def test_applied_path_records_both_audit_phases() -> None:
    writer = _Writer()
    terminal = await apply_shadow_reversion(command=_command(), writer=writer, recorded_at=NOW)
    assert terminal.outcome is ShadowReversionOutcome.APPLIED
    assert writer.calls == [
        "record_intent",
        "current_fence_matches",
        "apply",
        "record_terminal",
    ]


async def test_duplicate_application_is_not_reported_as_applied() -> None:
    writer = _Writer(applied=False)
    terminal = await apply_shadow_reversion(command=_command(), writer=writer, recorded_at=NOW)
    assert terminal.outcome is ShadowReversionOutcome.DUPLICATE


async def test_unrecorded_intent_blocks_the_attempt() -> None:
    writer = _Writer(intent_ok=False)
    terminal = await apply_shadow_reversion(command=_command(), writer=writer, recorded_at=NOW)
    assert terminal.outcome is ShadowReversionOutcome.REJECTED_INTENT_NOT_RECORDED
    assert "apply" not in writer.calls


async def test_stale_authorization_blocks_the_attempt() -> None:
    writer = _Writer(fence_ok=False)
    terminal = await apply_shadow_reversion(command=_command(), writer=writer, recorded_at=NOW)
    assert terminal.outcome is ShadowReversionOutcome.REJECTED_STALE_AUTHORIZATION
    assert "apply" not in writer.calls
    assert "record_terminal" in writer.calls


async def test_writer_failure_fails_closed() -> None:
    writer = _Writer(apply_error=RuntimeError("store down"))
    terminal = await apply_shadow_reversion(command=_command(), writer=writer, recorded_at=NOW)
    assert terminal.outcome is ShadowReversionOutcome.REJECTED_WRITER_FAILURE
    assert "RuntimeError" in terminal.detail


async def test_unrecorded_terminal_audit_is_reported() -> None:
    writer = _Writer(terminal_ok=False)
    terminal = await apply_shadow_reversion(command=_command(), writer=writer, recorded_at=NOW)
    assert terminal.outcome is ShadowReversionOutcome.REJECTED_TERMINAL_NOT_RECORDED


async def test_terminal_audit_exception_is_reported() -> None:
    writer = _Writer(terminal_error=OSError("audit store down"))
    terminal = await apply_shadow_reversion(command=_command(), writer=writer, recorded_at=NOW)
    assert terminal.outcome is ShadowReversionOutcome.REJECTED_TERMINAL_NOT_RECORDED


async def test_retry_reuses_the_same_idempotency_key() -> None:
    writer = _Writer()
    command = _command()
    await apply_shadow_reversion(command=command, writer=writer, recorded_at=NOW)
    await apply_shadow_reversion(command=command, writer=writer, recorded_at=NOW)
    assert writer.applied_keys == [command.idempotency_key, command.idempotency_key]


def test_writer_double_satisfies_the_protocol() -> None:
    assert isinstance(_Writer(), ShadowReversionWriter)


# ---------------------------------------------------------------------------
# Static proofs
# ---------------------------------------------------------------------------


def _imported_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.append(node.module)
            modules.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_reversion_command_never_reaches_the_promotion_registry() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = (
        "fdai.core.risk_gate",
        "fdai.core.executor",
        "fdai.core.workflow",
        "fdai.core.control_loop",
        "fdai.core.hil_resume",
        "fdai.delivery",
        "fdai.runtime",
        "fdai.composition",
    )
    for module in _imported_modules(tree):
        assert not module.startswith(forbidden), f"reversion command imports {module}"
    # Prose may name the registry; executable code may not reference it.
    identifiers = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert "ActionPromotionRegistry" not in identifiers
    assert "consider_promotion" not in identifiers


def test_no_authority_path_imports_the_reversion_command() -> None:
    """Whole-tree scan: no shipped module outside the package may reach the command.

    A hardcoded authority-root list would silently miss shipped directories such as
    ``core/decision_case``, ``core/execution_authorization``, and ``shared/providers``,
    so every shipped module is scanned instead.
    """
    violations = find_inertness_violations(
        SOURCE_ROOT,
        forbidden_modules=("fdai.core.standing_authority.shadow_reversion_command",),
        forbidden_symbols=frozenset(
            {
                "ShadowReversionCommand",
                "ShadowReversionIntent",
                "ShadowReversionOutcome",
                "ShadowReversionSafetyBindings",
                "ShadowReversionTerminal",
                "ShadowReversionWriter",
                "ExpectedAuthorizationState",
                "apply_shadow_reversion",
                "build_shadow_reversion_command",
                "shadow_reversion_command",
            }
        ),
    )
    assert violations == [], f"shipped modules reach the reversion command: {violations}"


def test_whole_tree_scan_covers_previously_unscanned_authority_surfaces() -> None:
    """Guard the guard: the scan must actually reach these shipped directories."""
    scanned = {path.relative_to(SOURCE_ROOT).parts[:2] for path in shipped_modules(SOURCE_ROOT)}
    for expected in (
        ("agents",),
        ("core", "risk_gate"),
        ("core", "executor"),
        ("core", "hil_resume"),
        ("core", "workflow"),
        ("core", "control_loop"),
        ("core", "decision_case"),
        ("core", "execution_authorization"),
        ("core", "execution_backend"),
        ("core", "recovery"),
        ("core", "scheduler"),
        ("shared", "providers"),
        ("delivery", "persistence"),
        ("runtime",),
    ):
        assert any(parts[: len(expected)] == expected for parts in scanned), (
            f"inertness scan does not reach {expected}"
        )


def test_scanner_resolves_relative_dynamic_and_re_export_import_forms(tmp_path: Path) -> None:
    """The scanner must catch the evasion forms a hardcoded prefix check misses."""
    root = tmp_path / "fdai"
    package = root / "core" / "probe"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    cases = {
        "absolute.py": (
            "from fdai.core.standing_authority.shadow_reversion_command import "
            "apply_shadow_reversion\n"
        ),
        "re_export.py": "from fdai.core.standing_authority import ShadowReversionCommand\n",
        "aliased.py": "import fdai.core.standing_authority.shadow_reversion_command as m\n",
        "relative.py": (
            "from ..standing_authority.shadow_reversion_command import "
            "build_shadow_reversion_command\n"
        ),
        "dynamic.py": (
            "import importlib\n"
            "m = importlib.import_module("
            '"fdai.core.standing_authority.shadow_reversion_command")\n'
        ),
        "clean.py": "from fdai.core.standing_authority import LeaseOutcome\n",
    }
    for name, body in cases.items():
        (package / name).write_text(body, encoding="utf-8")

    flagged = {
        violation.split(" -> ")[0]
        for violation in find_inertness_violations(
            root,
            forbidden_modules=("fdai.core.standing_authority.shadow_reversion_command",),
            forbidden_symbols=frozenset(
                {"ShadowReversionCommand", "apply_shadow_reversion", "shadow_reversion_command"}
            ),
        )
    }
    assert flagged == {
        "core/probe/absolute.py",
        "core/probe/re_export.py",
        "core/probe/aliased.py",
        "core/probe/relative.py",
        "core/probe/dynamic.py",
    }


def test_no_shipped_module_names_the_writer_or_orchestrator() -> None:
    """Text backstop for the structural Protocol and the un-exported orchestrator.

    A conforming adapter need never name ``ShadowReversionWriter`` (the Protocol is
    structural), so the orchestrator name is checked too: without it the orchestration
    cannot be driven.
    """
    hits = find_text_references(
        SOURCE_ROOT,
        frozenset({"ShadowReversionWriter", "apply_shadow_reversion"}),
        exclude=frozenset({MODULE_PATH}),
    )
    assert hits == [], f"shipped modules name the reversion mutation seam: {hits}"


def test_mutation_seam_is_not_in_the_package_namespace() -> None:
    """The writer Protocol and orchestrator stay reachable only by submodule import."""
    import fdai.core.standing_authority as package

    assert not hasattr(package, "ShadowReversionWriter")
    assert not hasattr(package, "apply_shadow_reversion")
    assert "ShadowReversionWriter" not in package.__all__
    assert "apply_shadow_reversion" not in package.__all__
    # The inert value types remain available for review and audit tooling.
    assert "ShadowReversionCommand" in package.__all__
    assert "build_shadow_reversion_command" in package.__all__
