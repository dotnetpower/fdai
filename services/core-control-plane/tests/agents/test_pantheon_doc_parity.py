"""Regression: pin pantheon names, layers, and ownership to the docs.

The machine-readable source of truth for the 15-agent pantheon is
``PANTHEON_SPECS`` in ``services/core-control-plane/src/fdai/agents/_framework/pantheon.py``. Two
human-readable docs paraphrase it:

- ``.github/instructions/agent-pantheon.instructions.md``
- ``docs/roadmap/agents/agent-pantheon.md``

If those docs drift from the code (a rename, an accidental omission, a
duplicated entry), this test catches it. It scans each doc for the 15
canonical names and asserts each one appears at least once.
"""

from __future__ import annotations

import re
from pathlib import Path

from fdai.agents import PANTHEON_NAMES, PANTHEON_SPECS
from fdai.agents._framework.action_run_state import ActionRunState

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DOC_PATHS = (
    _REPO_ROOT / ".github" / "instructions" / "agent-pantheon.instructions.md",
    _REPO_ROOT / "docs" / "roadmap" / "agents" / "agent-pantheon.md",
    _REPO_ROOT / "docs" / "roadmap" / "agents" / "agent-pantheon-ko.md",
)
_INSTRUCTIONS_PATH = _DOC_PATHS[0]
_CATALOG_DOC_PATHS = _DOC_PATHS[1:]
_LAYER_BY_NUMBER = {"1": "domain", "2": "pipeline", "3": "governance"}
_EXPECTED_PRIMARY_BEHAVIOR_EN = {
    "Odin": "arbitrate_domain_conflict",
    "Thor": (
        "dispatches one `ActionRun` per governed action, records lifecycle state, and owns "
        "no ActionType directly - see §7.1"
    ),
    "Forseti": (
        "produces verdicts and exact pre-execution prospective lineage; grounded RCA remains "
        "a core causal-hypothesis projection, not another bus topic; no executor role"
    ),
    "Huginn": (
        "ingest_event, normalize_change; verifies signed operator-request receipts and "
        "publishes inert schema-cluster evidence off path"
    ),
    "Heimdall": (
        "detect_anomaly, detect_drift, forecast, close_forecast_outcome, "
        "publish_evidence_conflict_revision, observe_terminal_action_effect, "
        "relay_recovery_effect_observation, validate_retrieval_failure, "
        "validate_rule_generation, notify_admin_privilege_violation"
    ),
    "Vidar": (
        "perform_rollback; accepts or holds DR failover contracts and records rollback "
        "rehearsal receipts"
    ),
    "Var": "approve_action, reject_action",
    "Bragi": (
        "translate_intent; records shadow-only intent-training evidence with reviewed "
        "activation required"
    ),
    "Saga": (
        "append_audit (normalize missing trace), escalate_to_github_issue; issue auto-close "
        "waits for Mimir promotion evidence and a clean 24 h recurrence window"
    ),
    "Mimir": (
        "promote_rule, revoke_rule, build_rule_generation; polls rule sources and records "
        "regression-backed promotion and deprecation evidence"
    ),
    "Muninn": "index_state, snapshot_state, seal_case_history",
    "Norns": (
        "propose_rule_candidate, analyze_case_history; emits inert quiet-window close_issue "
        "eligibility without mutating issues"
    ),
    "Njord": "propose_cost_action; retains the separate `Budget` graph lifecycle",
    "Freyr": (
        "forecasts capacity from bounded samples and emits shadow/HIL scale proposals "
        "through Forseti"
    ),
    "Loki": (
        "schedules always-HIL chaos proposals or visible holds and generates inert "
        "adversarial scenario candidates off path"
    ),
}


def _mentions(text: str, name: str) -> int:
    """Return the number of times ``name`` appears as a token in ``text``."""
    # Simple substring count is enough: the 15 names are unique tokens
    # that do not appear as prefixes of other English words in these
    # docs. Case-sensitive so 'thor' in inline URLs cannot mask a
    # missing capitalized 'Thor'.
    return text.count(name)


def test_all_pantheon_names_appear_in_each_doc() -> None:
    """Every canonical agent name MUST appear in every pantheon doc."""

    for doc_path in _DOC_PATHS:
        assert doc_path.is_file(), f"missing pantheon doc: {doc_path}"
        text = doc_path.read_text(encoding="utf-8")
        missing = [name for name in PANTHEON_NAMES if _mentions(text, name) == 0]
        assert not missing, (
            f"{doc_path.relative_to(_REPO_ROOT)} is missing pantheon "
            f"member(s): {sorted(missing)}. The machine-readable source is "
            "PANTHEON_SPECS in the Core service's "
            "fdai/agents/_framework/pantheon.py; the "
            f"docs paraphrase it. If a name changed in code, update the "
            f"doc to match."
        )


def test_pantheon_size_is_fifteen() -> None:
    """Sanity check the constant this test depends on."""
    assert len(PANTHEON_NAMES) == 15


def _catalog_rows(text: str) -> dict[str, tuple[str, tuple[str, ...], str, str]]:
    section = text.split("## 4.", 1)[1].split("### 4.1", 1)[0]
    rows: dict[str, tuple[str, tuple[str, ...], str, str]] = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 6 or cells[0] not in PANTHEON_NAMES:
            continue
        owns = tuple(item.strip().strip("`") for item in cells[3].split(",") if item.strip())
        rows[cells[0]] = (_LAYER_BY_NUMBER[cells[2]], owns, cells[4], cells[5])
    return rows


def _topic_rows(text: str) -> dict[str, tuple[str, tuple[str, ...]]]:
    section = text.split("### 6.1", 1)[1].split("Partitioning:", 1)[0]
    rows: dict[str, tuple[str, tuple[str, ...]]] = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 3 or not cells[0].startswith("object."):
            continue
        topics = tuple(item.strip().strip("`") for item in cells[0].split(","))
        publisher = cells[1].strip().strip("`")
        subscribers = tuple(
            sorted(
                name
                for name in PANTHEON_NAMES
                if re.search(rf"(?<![A-Za-z]){name}(?![A-Za-z])", cells[2])
            )
        )
        for topic in topics:
            rows[topic] = (publisher, subscribers)
    return rows


def _instruction_rows(
    text: str,
) -> dict[str, tuple[str, tuple[str, ...], tuple[str, ...], str, str]]:
    section = text.split("## 2.", 1)[1].split("## 3.", 1)[0]
    rows: dict[str, tuple[str, tuple[str, ...], tuple[str, ...], str, str]] = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 8:
            continue
        name = cells[0].strip("*")
        if name not in PANTHEON_NAMES:
            continue
        owns = tuple(item.strip().strip("`") for item in cells[3].split(",") if item.strip())
        subscribes = tuple(sorted(re.findall(r"object\.[a-z-]+", cells[5])))
        rows[name] = (cells[2], owns, subscribes, cells[6], cells[7])
    return rows


def _expected_catalog_llm(spec_name: str) -> str:
    spec = next(spec for spec in PANTHEON_SPECS if spec.name == spec_name)
    if spec.hot_path_llm:
        return "yes"
    if spec.off_path_llm:
        return "yes"
    return "no"


def _llm_cell_kind(cell: str) -> str:
    if cell.startswith("off-path"):
        return "off-path batch only"
    return "yes" if cell.startswith("yes") else "no"


def _section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def test_agent_catalog_layer_and_ownership_match_specs_in_both_locales() -> None:
    expected = {spec.name: (spec.layer.value, spec.owns) for spec in PANTHEON_SPECS}

    for doc_path in _CATALOG_DOC_PATHS:
        rows = _catalog_rows(doc_path.read_text(encoding="utf-8"))
        actual = {name: (layer, owns) for name, (layer, owns, _behavior, _llm) in rows.items()}
        assert actual == expected, doc_path.relative_to(_REPO_ROOT)


def test_agent_catalog_behavior_and_llm_match_specs_in_both_locales() -> None:
    english_rows = _catalog_rows(_CATALOG_DOC_PATHS[0].read_text(encoding="utf-8"))
    assert {
        name: behavior for name, (_layer, _owns, behavior, _llm) in english_rows.items()
    } == _EXPECTED_PRIMARY_BEHAVIOR_EN

    for doc_path in _CATALOG_DOC_PATHS:
        rows = _catalog_rows(doc_path.read_text(encoding="utf-8"))
        actual_llm = {name: _llm_cell_kind(llm) for name, (*_rest, llm) in rows.items()}
        expected_llm = {spec.name: _expected_catalog_llm(spec.name) for spec in PANTHEON_SPECS}
        assert actual_llm == expected_llm, doc_path.relative_to(_REPO_ROOT)


def test_topic_subscriber_tables_match_specs_in_both_locales() -> None:
    expected: dict[str, tuple[str, tuple[str, ...]]] = {}
    for spec in PANTHEON_SPECS:
        for topic in spec.publishes:
            subscribers = tuple(
                sorted(
                    subscriber.name
                    for subscriber in PANTHEON_SPECS
                    if topic in subscriber.subscribes
                )
            )
            expected[topic] = (spec.name, subscribers)

    for doc_path in _CATALOG_DOC_PATHS:
        rows = _topic_rows(doc_path.read_text(encoding="utf-8"))
        assert rows == expected, doc_path.relative_to(_REPO_ROOT)


def test_instruction_subscription_table_matches_specs() -> None:
    rows = _instruction_rows(_INSTRUCTIONS_PATH.read_text(encoding="utf-8"))
    expected = {
        spec.name: (
            spec.layer.value,
            spec.owns,
            tuple(sorted(spec.subscribes)),
            "yes" if spec.hot_path_llm else "off-path batch only" if spec.off_path_llm else "no",
            "yes" if spec.hard_dependency else "no",
        )
        for spec in PANTHEON_SPECS
    }
    actual = {
        name: (layer, owns, subscribes, _llm_cell_kind(llm), hard_dep.lower().strip("*"))
        for name, (layer, owns, subscribes, llm, hard_dep) in rows.items()
    }
    assert actual == expected


def test_action_run_lifecycle_states_match_code_in_both_locales() -> None:
    expected_states = {state.value for state in ActionRunState}
    for doc_path in _CATALOG_DOC_PATHS:
        text = doc_path.read_text(encoding="utf-8")
        lifecycle = _section(text, "### 7.2", "### 7.3")
        code_block = lifecycle.split("```", 2)[1]
        states = set(
            re.findall(r"^\s*(?:->\s+)?([a-z_]+)(?:\s+\(|$)", code_block, flags=re.MULTILINE)
        )
        assert states == expected_states, doc_path.relative_to(_REPO_ROOT)


def test_action_identity_batch_and_rate_limit_vocabulary_match_code() -> None:
    forbidden = (
        r"`action_run_id`",
        r"per-attempt `attempt_id`",
        r"`attempt_id` are idempotency keys",
        r"RateLimitExceeded",
    )
    required = ("action_run_identity()", "rate_limit_exceeded")
    for doc_path in _CATALOG_DOC_PATHS:
        text = doc_path.read_text(encoding="utf-8")
        for token in forbidden:
            assert not re.search(token, text), (
                f"{doc_path.relative_to(_REPO_ROOT)} still documents {token}"
            )
        for token in required:
            assert token in text, f"{doc_path.relative_to(_REPO_ROOT)} missing {token}"
