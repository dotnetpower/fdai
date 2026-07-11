"""Structural drift guards for the split contract-models package (#18 G-4).

The 800-LOC monolith at ``fdai.shared.contracts.models`` became a
per-domain package. These tests pin the shape so a stray missing
re-export, a renamed enum value, or a broken invariant (frozen /
extra=forbid) surfaces as a test failure instead of a runtime bug at
some downstream callsite.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

import fdai.shared.contracts.models as models

_MODELS_DIR = Path(models.__file__).parent
_SUBMODULE_NAMES = tuple(
    sorted(
        name
        for _finder, name, ispkg in pkgutil.iter_modules([str(_MODELS_DIR)])
        if not ispkg and not name.startswith("_")  # skip _base
    )
)


# ---------------------------------------------------------------------------
# H1: __all__ parity - every re-exported symbol resolves, and every public
# submodule symbol is re-exported at the package level.
# ---------------------------------------------------------------------------


def test_all_exports_resolve() -> None:
    for name in models.__all__:
        assert hasattr(models, name), f"{name!r} is listed in models.__all__ but is not importable"


def test_every_public_submodule_symbol_is_re_exported() -> None:
    exported = set(models.__all__)
    missing: dict[str, list[str]] = {}
    for name in _SUBMODULE_NAMES:
        sub = importlib.import_module(f"fdai.shared.contracts.models.{name}")
        # Submodules declare their own __all__; anything in there is public
        # and MUST be re-exported at the package facade.
        sub_all = getattr(sub, "__all__", ())
        gap = [s for s in sub_all if s not in exported]
        if gap:
            missing[name] = gap
    assert not missing, (
        "Public symbols are missing from models/__init__.py __all__: "
        f"{missing}. Add them to the facade so callers do not need to "
        "reach into the submodule."
    )


def test_base_submodule_symbols_are_re_exported() -> None:
    # _base is intentionally underscore-prefixed but its symbols
    # (_Base, SemVer, IdempotencyKey) are legitimate public API.
    from fdai.shared.contracts.models import _base as base_mod

    exported = set(models.__all__)
    gap = [s for s in base_mod.__all__ if s not in exported]
    assert not gap, f"_base symbols missing from facade __all__: {gap}"


# ---------------------------------------------------------------------------
# H2: enum-value pinning. Renaming an enum value silently breaks the JSON
# schema compat because these values are the wire strings. Pin them here.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "enum_cls_name,expected_values",
    [
        ("Tier", {"t0", "t1", "t2"}),
        ("Decision", {"auto", "hil", "abstain", "deny"}),
        ("Mode", {"shadow", "enforce"}),
        (
            "Autonomy",
            {"enforce_auto", "enforce_hil", "shadow_only"},
        ),
        (
            "CeilingRole",
            {"reader", "contributor", "approver", "owner"},
        ),
        (
            "ExecutionPath",
            {"pr_native", "direct_api", "pr_manual", "tool_call"},
        ),
        ("EnvScope", {"prod", "non_prod", "any"}),
        (
            "IncidentState",
            {"open", "triaging", "mitigated", "resolved", "closed"},
        ),
        (
            "IncidentSeverity",
            {"sev1", "sev2", "sev3", "sev4", "sev5"},
        ),
        ("WorkflowTriggerKind", {"signal", "schedule"}),
    ],
)
def test_enum_values_are_pinned(enum_cls_name: str, expected_values: set[str]) -> None:
    cls = getattr(models, enum_cls_name)
    actual = {member.value for member in cls}
    assert actual == expected_values, (
        f"{enum_cls_name} enum values changed: expected {expected_values}, "
        f"got {actual}. If this is intentional, update the JSON schemas + "
        "downstream fork configs + this test in one PR."
    )


# ---------------------------------------------------------------------------
# H3+H4: safety invariants on _Base (frozen + extra=forbid).
# ---------------------------------------------------------------------------


def test_action_model_is_frozen() -> None:
    from datetime import UTC, datetime
    from uuid import uuid4

    action = models.Action(
        schema_version="1.0.0",
        action_id=uuid4(),
        idempotency_key="k",
        event_id=uuid4(),
        action_type="noop",
        target_resource_ref="rg-a",
        operation=models.Operation.TAG,
        stop_condition="never",
        rollback_ref=models.RollbackRef(kind=models.RollbackKind.PR_REVERT),
        blast_radius=models.BlastRadius(scope=models.BlastRadiusScope.RESOURCE),
        mode=models.Mode.SHADOW,
        citing_rules=["r-1"],
        created_at=datetime.now(UTC),
    )
    with pytest.raises(ValidationError):
        action.stop_condition = "changed"  # type: ignore[misc]


def test_action_model_forbids_unknown_fields() -> None:
    from datetime import UTC, datetime
    from uuid import uuid4

    with pytest.raises(ValidationError) as info:
        models.Action(  # type: ignore[call-arg]
            schema_version="1.0.0",
            action_id=uuid4(),
            idempotency_key="k",
            event_id=uuid4(),
            action_type="noop",
            target_resource_ref="rg-a",
            operation=models.Operation.TAG,
            stop_condition="never",
            rollback_ref=models.RollbackRef(kind=models.RollbackKind.PR_REVERT),
            blast_radius=models.BlastRadius(scope=models.BlastRadiusScope.RESOURCE),
            mode=models.Mode.SHADOW,
            citing_rules=["r-1"],
            created_at=datetime.now(UTC),
            surprise_field="nope",  # unknown - must be rejected
        )
    assert "surprise_field" in str(info.value)


# ---------------------------------------------------------------------------
# H5: per-file LOC ceiling inside the split package (self-enforcement).
# ---------------------------------------------------------------------------


def test_no_split_file_exceeds_400_loc() -> None:
    over = []
    for path in sorted(_MODELS_DIR.glob("*.py")):
        loc = path.read_text().count("\n")
        if loc > 400:
            over.append((path.name, loc))
    assert not over, (
        f"models/ split files exceed the 400-LOC per-domain ceiling: {over}. "
        "Split further along a natural axis (enum group, ObjectType, ...) "
        "or move a class into its own file."
    )


# ---------------------------------------------------------------------------
# H7: domain isolation. Each submodule may import from _base + enums + its
# own ontology parents (workflow -> ontology, incident -> nothing beyond
# enums), but never sideways from a peer domain.
# ---------------------------------------------------------------------------


_ALLOWED_INTRA_MODEL_IMPORTS: dict[str, set[str]] = {
    "action": {"_base", "enums"},
    "event": {"_base", "enums"},
    "incident": {"_base", "enums"},
    "rule": {"_base", "enums"},
    "ontology": {"_base", "enums"},
    "workflow": {"_base", "enums", "ontology"},  # Workflow -> PromotionGate
}


@pytest.mark.parametrize("submodule", sorted(_ALLOWED_INTRA_MODEL_IMPORTS))
def test_submodule_only_imports_from_allowed_peers(submodule: str) -> None:
    path = _MODELS_DIR / f"{submodule}.py"
    body = path.read_text()
    # Look for 'from ._X' or 'from .X' relative imports.
    allowed = _ALLOWED_INTRA_MODEL_IMPORTS[submodule]
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped.startswith("from ."):
            continue
        # form: from ._base import X  or  from .ontology import Y
        rest = stripped[len("from .") :]
        peer = rest.split(" ", 1)[0].lstrip("_")
        if peer.startswith(("_",)):
            peer = peer[1:]
        # `._base` -> `_base` (strip the leading underscore for lookup)
        raw_peer = rest.split(" ", 1)[0]
        actual = raw_peer.lstrip(".")  # keeps leading _
        actual_short = actual.lstrip("_")
        if actual not in {"_base", "enums", *(_ALLOWED_INTRA_MODEL_IMPORTS[submodule])}:
            # Only accept exact allowed names (allow underscore prefix).
            key = actual if actual in allowed else actual_short
            assert key in allowed, (
                f"models/{submodule}.py imports from models/{actual}.py which "
                f"is not in the allowlist {sorted(allowed)}. Cross-domain "
                "coupling is a smell; extract shared types into _base or enums."
            )


# ---------------------------------------------------------------------------
# H10: __all__ has no duplicate entries (governance-cleanliness).
# ---------------------------------------------------------------------------


def test_all_has_no_duplicates() -> None:
    exported = models.__all__
    assert len(exported) == len(set(exported)), (
        "models.__all__ contains duplicate entries: "
        f"{sorted(x for x in set(exported) if exported.count(x) > 1)}"
    )


# ---------------------------------------------------------------------------
# H11: every re-exported name that resolves to a class MUST be a pydantic
# BaseModel or a StrEnum - a stray helper function slipping into __all__
# would break the "these are contract data models" contract.
# ---------------------------------------------------------------------------


def test_every_exported_class_is_a_model_or_enum() -> None:
    from enum import StrEnum

    # Allow: a small set of type aliases and one dict constant.
    allowed_non_class = {"IdempotencyKey", "SemVer", "CEILING_ROLE_RANK"}
    offenders: list[str] = []
    for name in models.__all__:
        obj = getattr(models, name)
        if name in allowed_non_class:
            continue
        if isinstance(obj, type) and issubclass(obj, (BaseModel, StrEnum)):
            continue
        offenders.append(f"{name} ({type(obj).__name__})")
    assert not offenders, (
        "Non-model, non-enum symbols leaked into models.__all__: "
        f"{offenders}. Move them out of the contracts package."
    )


def test_contract_base_is_the_public_alias_of_underscore_base() -> None:
    # H9: forks and downstream extensions should subclass ContractBase, not
    # the underscore-prefixed name. The two MUST refer to the same class so
    # existing internal imports do not break.
    assert models.ContractBase is models._Base  # type: ignore[attr-defined]
    assert models.ContractBase.__name__ == "ContractBase"


def test_contract_base_enforces_frozen_and_extra_forbid() -> None:
    # H9 (companion): a fork model subclassing ContractBase inherits both
    # invariants without re-declaring model_config.
    class ForkModel(models.ContractBase):
        name: str

    inst = ForkModel(name="ok")
    with pytest.raises(ValidationError):
        inst.name = "changed"
    with pytest.raises(ValidationError):
        ForkModel(name="ok", surprise="nope")
