"""Operator console CLI REPL entry point (Day 1 - operator-console.md).

Minimal interactive shell that composes the shipped rule + ActionType
catalogs into a :class:`ConversationCoordinator` with a single Day-1
tool (:class:`ExploreCatalogTool`) and reads utterances from stdin,
printing results to stdout.

Usage::

    uv run python -m tools.chat --role reader
    uv run python -m tools.chat --role reader --json <<< "explore_catalog storage"
    uv run python -m tools.chat --help

Exit codes:

- ``0`` clean session end (EOF on stdin or ``:quit`` verb).
- ``2`` invalid config (bad env or arguments).
- ``3`` unrecoverable channel error (stdin closed unexpectedly, ...).

The shell is intentionally sync + tiny: it delegates all decision-making
to the coordinator, keeps no state the audit log does not, and prints
JSONL when ``--json`` is set so it composes with pipes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from aiopspilot.core.conversation import (
    AbstainResult,
    ActivateBreakGlassTool,
    ApproveHilTool,
    AuditWriter,
    ConversationCoordinator,
    ConversationSession,
    CoordinatorConfig,
    DescribeEventTool,
    ExplainVerdictTool,
    ExploreCatalogTool,
    ListHilTool,
    Principal,
    QueryAuditTool,
    QueryInventoryTool,
    Role,
    RunRunbookTool,
    SimulateChangeTool,
    ToolResult,
)
from aiopspilot.core.executor.action_builder import ActionBuilder
from aiopspilot.core.executor.renderer import TemplateRenderer
from aiopspilot.core.tiers.t0_deterministic import T0Engine
from aiopspilot.core.tiers.t0_deterministic.engine import AbstainEvaluator
from aiopspilot.core.tiers.t0_deterministic.index import RuleIndex
from aiopspilot.core.trust_router import TrustRouter
from aiopspilot.rule_catalog.schema.action_type import load_action_type_catalog
from aiopspilot.rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
)
from aiopspilot.rule_catalog.schema.rule import load_rule_catalog
from aiopspilot.shared.contracts.models import OntologyActionType, Rule
from aiopspilot.shared.contracts.registry import PackageResourceSchemaRegistry
from aiopspilot.shared.providers.testing.break_glass_pager import (
    InMemoryBreakGlassPager,
)
from aiopspilot.shared.providers.testing.hil_registry import (
    InMemoryHilApprovalRegistry,
)
from aiopspilot.shared.providers.testing.runbook_registry import (
    InMemoryRunbookRegistry,
)
from aiopspilot.shared.providers.testing.state_store import InMemoryStateStore


def _repo_root() -> Path:
    """Locate the repo root by walking up looking for ``rule-catalog/``."""

    override = os.environ.get("AIOPSPILOT_CATALOG_ROOT")
    if override:
        candidate = Path(override)
        if not candidate.is_dir():
            raise FileNotFoundError(f"AIOPSPILOT_CATALOG_ROOT={override!r} is not a directory")
        return candidate.parent
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "rule-catalog" / "catalog").is_dir():
            return parent
    for absolute in (Path("/app"), Path.cwd()):
        if (absolute / "rule-catalog" / "catalog").is_dir():
            return absolute
    raise FileNotFoundError("Could not locate rule-catalog/. Set AIOPSPILOT_CATALOG_ROOT.")


def _load_catalogs(repo_root: Path) -> tuple[list[Rule], list[OntologyActionType]]:
    registry = PackageResourceSchemaRegistry()
    catalog_root = repo_root / "rule-catalog"

    # Resource types (required by rule loader).
    rt_manifest_path = catalog_root / "vocabulary" / "resource-types.yaml"
    if not rt_manifest_path.is_file():
        return [], list(
            load_action_type_catalog(catalog_root / "action-types", schema_registry=registry)
        )

    import yaml

    with rt_manifest_path.open() as f:
        rt_mapping = yaml.safe_load(f)
    resource_types = load_resource_type_registry_from_mapping(rt_mapping)
    action_types = load_action_type_catalog(catalog_root / "action-types", schema_registry=registry)
    rule_catalog_result = load_rule_catalog(
        catalog_root / "catalog",
        schema_registry=registry,
        resource_types=resource_types,
        action_types=action_types,
    )
    return list(rule_catalog_result), list(action_types)


def _print_line(payload: Any, *, json_mode: bool) -> None:
    """Write one response line to stdout.

    In JSON mode every result is a single JSON object per line. In text
    mode the coordinator's ``preview`` string is printed followed by
    the tool inventory when relevant.
    """

    if json_mode:
        sys.stdout.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")
        sys.stdout.flush()
        return

    if isinstance(payload, dict):
        preview = payload.get("preview")
        status = payload.get("status")
        header = f"[{status}] {preview}" if preview else str(payload)
        sys.stdout.write(header + "\n")
        data = payload.get("data") or {}
        for rule in data.get("rules") or []:
            sys.stdout.write(
                f"  rule       {rule.get('id')}  "
                f"({rule.get('severity')}, {rule.get('resource_type')})\n"
            )
        for at in data.get("action_types") or []:
            sys.stdout.write(
                f"  action     {at.get('id')}  ({at.get('category')}, {at.get('operation')})\n"
            )
        tool_inventory = payload.get("tool_inventory")
        if tool_inventory:
            sys.stdout.write(f"  try one of: {', '.join(tool_inventory)}\n")
        sys.stdout.flush()
    else:
        sys.stdout.write(str(payload) + "\n")
        sys.stdout.flush()


def _result_to_dict(result: ToolResult | AbstainResult) -> dict[str, Any]:
    if isinstance(result, ToolResult):
        return {
            "kind": "tool_result",
            "status": result.status,
            "preview": result.preview,
            "data": dict(result.data),
            "evidence_refs": list(result.evidence_refs),
        }
    return {
        "kind": "abstain",
        "status": "abstain",
        "preview": result.reason,
        "tool_inventory": list(result.tool_inventory),
    }


def _parse_role(raw: str) -> Role:
    try:
        return Role(raw.lower())
    except ValueError as exc:  # pragma: no cover - argparse validates first
        raise argparse.ArgumentTypeError(
            f"unknown role {raw!r}; use one of {[r.value for r in Role]}"
        ) from exc


def _read_lines(stream: Iterable[str]) -> Iterable[str]:
    for line in stream:
        stripped = line.rstrip("\n").rstrip("\r")
        if not stripped:
            continue
        yield stripped


class _EmptyInventory:
    """Async-iterator inventory that yields no batches.

    Used by the CLI when no inventory fixture is available. The
    :class:`QueryInventoryTool` will always return an ``abstain``
    result against it; a fork that binds a real inventory sees rows.
    """

    async def full_snapshot(self, since: str | None = None):  # noqa: ARG002
        # Empty async iterator; break out immediately.
        if False:  # pragma: no cover - unreachable yield keeps this a generator
            yield None

    async def delta(self, cursor: str):  # noqa: ARG002
        if False:  # pragma: no cover
            yield None


def _build_tools(
    *,
    rules: list[Rule],
    action_types: list[OntologyActionType],
    repo_root: Path,
) -> list[Any]:
    """Wire every shipped SystemConsoleTool (read + write) for the CLI session.

    All backends default to in-memory fakes so the CLI works out of the
    box. A fork binds real providers via the composition root; this
    helper is CLI-only. The audit store is shared between the read
    (query_audit / explain_verdict) and write (simulate_change /
    approve_hil / run_runbook / activate_break_glass) tools so a
    session can inspect its own effects in one place.
    """

    rule_index = RuleIndex.build(rules)
    trust_router = TrustRouter(index=rule_index)
    t0_engine = T0Engine(index=rule_index, evaluator=AbstainEvaluator())
    audit_store = InMemoryStateStore()
    audit_writer = AuditWriter(audit_store=audit_store)
    inventory = _EmptyInventory()

    # Write-tool dependencies.
    action_types_by_name = {a.name: a for a in action_types}
    rules_by_id = {r.id: r for r in rules}
    action_builder = ActionBuilder(action_types_by_name=action_types_by_name)
    remediation_root = repo_root / "rule-catalog" / "remediation"
    template_renderer = TemplateRenderer(remediation_root=remediation_root)
    hil_registry = InMemoryHilApprovalRegistry()
    runbook_registry = InMemoryRunbookRegistry()
    break_glass_pager = InMemoryBreakGlassPager()

    tools: list[Any] = [
        ExploreCatalogTool(rules=rules, action_types=action_types),
        DescribeEventTool(trust_router=trust_router, t0_engine=t0_engine),
        ExplainVerdictTool(audit_reader=audit_store),
        QueryAuditTool(audit_reader=audit_store),
        QueryInventoryTool(inventory=inventory),
        SimulateChangeTool(
            trust_router=trust_router,
            t0_engine=t0_engine,
            action_builder=action_builder,
            template_renderer=template_renderer,
            rules_by_id=rules_by_id,
            audit_writer=audit_writer,
        ),
        ListHilTool(registry=hil_registry),
        ApproveHilTool(
            registry=hil_registry,
            audit_writer=audit_writer,
            known_action_kinds=frozenset(action_types_by_name),
        ),
        RunRunbookTool(registry=runbook_registry, audit_writer=audit_writer),
        ActivateBreakGlassTool(pager=break_glass_pager, audit_writer=audit_writer),
    ]
    return tools


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aiopspilot-chat",
        description="AIOpsPilot operator console REPL (Day 1).",
    )
    parser.add_argument(
        "--role",
        type=_parse_role,
        default=Role.READER,
        help="RBAC role for this session (default: reader).",
    )
    parser.add_argument(
        "--principal-id",
        default="cli-local",
        help="Principal id recorded on the session (default: cli-local).",
    )
    parser.add_argument(
        "--json",
        dest="json_mode",
        action="store_true",
        help="Emit JSONL instead of formatted text.",
    )
    parser.add_argument(
        "--catalog-root",
        default=None,
        help=(
            "Override the rule-catalog root directory. "
            "Same effect as setting AIOPSPILOT_CATALOG_ROOT."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.catalog_root:
        os.environ["AIOPSPILOT_CATALOG_ROOT"] = args.catalog_root

    try:
        repo_root = _repo_root()
        rules, action_types = _load_catalogs(repo_root)
    except FileNotFoundError as exc:
        sys.stderr.write(f"chat: {exc}\n")
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI boundary, print + exit
        sys.stderr.write(f"chat: catalog load failed: {exc}\n")
        return 2

    tools = _build_tools(rules=rules, action_types=action_types, repo_root=repo_root)
    coordinator = ConversationCoordinator(tools=tools, config=CoordinatorConfig())
    principal = Principal(id=args.principal_id, role=args.role, display_name=args.principal_id)
    session = ConversationSession(
        session_id=str(uuid.uuid4()),
        principal=principal,
        channel_id="cli",
    )

    if not args.json_mode:
        sys.stdout.write(
            f"aiopspilot-chat: session={session.session_id[:8]} "
            f"role={principal.role.value} "
            f"rules={len(rules)} action_types={len(action_types)}\n"
        )
        sys.stdout.write(f"tools: {', '.join(coordinator.tool_names)}\n")
        sys.stdout.write("type an intent (e.g. 'explore_catalog storage'), ':quit' to exit.\n")
        sys.stdout.flush()

    for line in _read_lines(sys.stdin):
        if line.strip().lower() in (":quit", ":exit", ":q"):
            break
        try:
            result = coordinator.handle_turn(session=session, message=line)
        except KeyError as exc:
            sys.stderr.write(f"chat: {exc}\n")
            return 3
        _print_line(_result_to_dict(result), json_mode=args.json_mode)

    return 0


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    raise SystemExit(main())
