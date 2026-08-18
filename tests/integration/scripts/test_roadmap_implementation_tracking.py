from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_module() -> ModuleType:
    path = REPO_ROOT / "scripts/quality/architecture/check-roadmap-implementation-tracking.py"
    spec = importlib.util.spec_from_file_location("check_roadmap_implementation_tracking", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ledger(
    *,
    state: str = "implemented",
    history_state: str = "implemented",
    extra_history: str = "",
    leading_history: str = "",
) -> str:
    history_row = (
        f"| 2026-08-14 | {history_state} | Added the loader. | "
        "current change; focused tests pass. | Validate runtime evidence. |"
    )
    return f"""# Owner

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Loader | {state} | `src/loader.py` and focused tests | Bounded path. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
{leading_history}{history_row}
{extra_history}
### Remaining work

- [ ] Record a governed runtime receipt for the loader.
"""


def test_complete_ledger_is_accepted() -> None:
    module = _load_module()

    assert module.ledger_violations(_ledger()) == []


def test_missing_required_subsection_is_rejected() -> None:
    module = _load_module()
    content = _ledger().replace("### Remaining work", "### Follow-up")

    errors = module.ledger_violations(content)

    assert errors == ["implementation status must contain the three required H3 headings in order"]


def test_unknown_scope_state_is_rejected() -> None:
    module = _load_module()

    errors = module.ledger_violations(_ledger(state="partial"))

    assert any("unsupported state 'partial'" in error for error in errors)


def test_withdrawn_is_accepted_only_in_implementation_history() -> None:
    module = _load_module()

    assert module.ledger_violations(_ledger(history_state="withdrawn")) == []
    errors = module.ledger_violations(_ledger(state="withdrawn"))

    assert any("scope row 1 has unsupported state 'withdrawn'" in error for error in errors)


def test_existing_history_rows_are_append_only() -> None:
    module = _load_module()
    previous = _ledger()
    current = _ledger().replace("Added the loader.", "Reworded the old transition.")

    errors = module.ledger_violations(current, previous)

    assert any("history is append-only" in error for error in errors)
    # Naming the lost row is the difference between a five minute fix and an hour of bisecting.
    assert any("2026-08-14" in error and "Added the loader." in error for error in errors)


def test_a_merge_may_interleave_a_newer_row_ahead_of_a_recorded_row() -> None:
    module = _load_module()
    previous = _ledger()
    merged = _ledger(
        leading_history=(
            "| 2026-08-15 | implemented | Landed on another branch. | `src/other.py` | None. |\n"
        )
    )

    # Git orders two branches' appended rows however the merge resolves, so position cannot be
    # the contract; requiring an ordered prefix made it unsatisfiable for concurrent branches.
    assert module.ledger_violations(merged, previous) == []


def test_removing_one_of_two_identical_rows_is_rejected() -> None:
    module = _load_module()
    duplicate = (
        "| 2026-08-14 | implemented | Added the loader. | "
        "current change; focused tests pass. | Validate runtime evidence. |\n"
    )

    errors = module.ledger_violations(_ledger(), _ledger(extra_history=duplicate))

    assert any("history is append-only" in error for error in errors)


def test_new_history_rows_may_be_appended() -> None:
    module = _load_module()
    previous = _ledger()
    added = (
        "| 2026-08-15 | validated | Captured a runtime receipt. | "
        "`evidence/receipt.json` | No remaining work. |\n"
    )

    assert module.ledger_violations(_ledger(extra_history=added), previous) == []


def test_non_owner_roadmap_documents_are_exempt() -> None:
    module = _load_module()

    assert module.is_exempt("docs/roadmap/README.md")
    assert module.is_exempt("docs/roadmap/architecture/index.md")
    assert module.is_exempt("docs/roadmap/architecture/fdai-constitution.md")
    assert module.is_exempt("docs/roadmap/architecture/decisions/0001-example.md")
    assert module.is_exempt("docs/roadmap/architecture/owner-ko.md")
    assert not module.is_exempt("docs/roadmap/architecture/owner.md")


def test_all_docs_returns_only_tracked_canonical_owners(monkeypatch) -> None:
    module = _load_module()
    tracked = "\n".join(
        (
            "docs/roadmap/README.md",
            "docs/roadmap/architecture/decisions/0001-example.md",
            "docs/roadmap/architecture/fdai-constitution.md",
            "docs/roadmap/architecture/owner-ko.md",
            "docs/roadmap/architecture/owner.md",
            "docs/roadmap/interfaces/contract.md",
            "docs/roadmap/interfaces/example.json",
        )
    )
    monkeypatch.setattr(
        module,
        "_run_git",
        lambda *args, **kwargs: type("Result", (), {"stdout": tracked})(),
    )

    assert module._all_docs() == (
        "docs/roadmap/architecture/owner.md",
        "docs/roadmap/interfaces/contract.md",
    )
