"""Prove complete decision-critical evidence admission coverage.

Every registered positive decision boundary must resolve its decision-critical
evidence through the shared admission contract and must fail closed when no
admission is available. The inventory in `config/decision-boundary-inventory.json`
is the declared complete list, and this check enforces coverage in both
directions: every registered boundary is really wired to the shared contract, and
every module that touches the shared contract or declares an evidence purpose is
really registered.

Module-level facts alone cannot prove that. A module can import and call the
shared assessor and still return a positive outcome on a path that never reaches
that call. So each boundary additionally declares its decision call sites, and
this check runs a control-flow-aware dominance analysis over each declared
function: every exit that is not an explicitly declared fail-closed exit, and not
an explicitly declared delegation to another registered decision, MUST be
dominated by a live admission evaluation. A discarded result, a call reached on
only one branch, and an assessor imported from another module are all rejected,
because none of them proves the decision was actually admitted.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INVENTORY = Path("config/decision-boundary-inventory.json")
BOUNDARY_ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
PURPOSE_CONSTANT_PATTERN = re.compile(r"^[A-Z0-9_]+_EVIDENCE_PURPOSE$")
REQUIRED_BOUNDARY_KEYS = frozenset(
    {"id", "positive_decision", "module", "purpose_constant", "purpose_id", "tests", "decisions"}
)
REQUIRED_NEGATIVE_CLASSES = (
    "missing",
    "stale",
    "incomplete",
    "conflicting",
    "synthetic",
    "wrong-purpose",
    "wrong-scope",
)
GUARD_KINDS = frozenset({"returns", "raises"})

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


class InventoryError(Exception):
    """The inventory document itself cannot be interpreted."""


@dataclass(frozen=True, slots=True)
class ModuleFacts:
    """Structural facts extracted from one module without importing it."""

    tree: ast.Module
    imports_assessor: bool
    calls_assessor: bool
    purpose_constants: Mapping[str, str | None]
    fails_closed_on_absent_admission: bool
    import_sources: Mapping[str, str]
    functions: Mapping[str, FunctionNode]


@dataclass(frozen=True, slots=True)
class GuardSpec:
    """One callable whose evaluation admits, or refuses to admit, a decision."""

    name: str
    kind: str


@dataclass
class ExitRecord:
    """One way a declared decision function can hand a result back."""

    label: str
    expression: str
    guarded: bool
    line: int


@dataclass
class BlockResult:
    """Fall-through state of one analyzed statement block."""

    guarded: bool | None
    exits: list[ExitRecord] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)


def _load_inventory(path: Path) -> Mapping[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise InventoryError(f"inventory not found: {path}") from error
    except json.JSONDecodeError as error:
        raise InventoryError(f"inventory is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise InventoryError("inventory must be a JSON object")
    return document


def _decision_surface_digest(root: Path, document: Mapping[str, Any]) -> str:
    """Hash exact registered decisions, helpers, and their guard imports."""

    assessor = str(document["shared_admission"]["assessor"])
    entries: list[tuple[str, tuple[Mapping[str, Any], ...]]] = []
    for boundary in document.get("boundaries", []):
        if not isinstance(boundary, dict) or not isinstance(boundary.get("module"), str):
            continue
        decisions = tuple(
            decision for decision in boundary.get("decisions", []) if isinstance(decision, dict)
        )
        entries.append((str(boundary["module"]), decisions))
    for helper in document.get("admission_helpers", []):
        if not isinstance(helper, dict) or not isinstance(helper.get("module"), str):
            continue
        decisions = tuple(
            {"function": function, "guards": []}
            for function in helper.get("functions", [])
            if isinstance(function, str)
        )
        entries.append((str(helper["module"]), decisions))
    records: list[dict[str, object]] = []
    for module_ref, decisions in sorted(entries, key=lambda item: item[0]):
        path = root / module_ref
        if not path.is_file():
            continue
        source_lines = path.read_text(encoding="utf-8").splitlines()
        facts = _module_facts(path, assessor)
        for decision in decisions:
            qualified = decision.get("function")
            if not isinstance(qualified, str):
                continue
            function = facts.functions.get(qualified)
            if function is None:
                continue
            records.append(
                {
                    "module": module_ref,
                    "function": qualified,
                    "source": "\n".join(source_lines[function.lineno - 1 : function.end_lineno]),
                    "guard_imports": {
                        str(guard.get("name")): facts.import_sources.get(str(guard.get("name")))
                        for guard in decision.get("guards", [])
                        if isinstance(guard, dict)
                    },
                }
            )
    encoded = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _collect_functions(tree: ast.Module) -> dict[str, FunctionNode]:
    functions: dict[str, FunctionNode] = {}

    def walk(node: ast.AST, prefix: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                walk(child, [*prefix, child.name])
            elif isinstance(child, FunctionNode):
                qualified = ".".join([*prefix, child.name])
                functions[qualified] = child
                walk(child, [*prefix, child.name])

    walk(tree, [])
    return functions


def _module_facts(path: Path, assessor: str) -> ModuleFacts:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports_assessor = False
    calls_assessor = False
    purpose_constants: dict[str, str | None] = {}
    import_sources: dict[str, str] = {}
    fails_closed = False
    admission_hints = ("admission", "decision_evidence")
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound = alias.asname or alias.name
                import_sources[bound] = f"{node.module or ''}.{alias.name}"
                if alias.name == assessor:
                    imports_assessor = True
        elif isinstance(node, ast.Call):
            function = node.func
            name = getattr(function, "id", None) or getattr(function, "attr", None)
            if name == assessor:
                calls_assessor = True
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if not PURPOSE_CONSTANT_PATTERN.match(target.id):
                    continue
                value = node.value
                literal = value.value if isinstance(value, ast.Constant) else None
                purpose_constants[target.id] = literal if isinstance(literal, str) else None
        elif isinstance(node, ast.Compare):
            if not any(isinstance(operator, ast.Is | ast.IsNot) for operator in node.ops):
                continue
            if not any(
                isinstance(comparator, ast.Constant) and comparator.value is None
                for comparator in node.comparators
            ):
                continue
            left = ast.unparse(node.left).lower()
            if any(hint in left for hint in admission_hints):
                fails_closed = True
    return ModuleFacts(
        tree=tree,
        imports_assessor=imports_assessor,
        calls_assessor=calls_assessor,
        purpose_constants=purpose_constants,
        fails_closed_on_absent_admission=fails_closed,
        import_sources=import_sources,
        functions=_collect_functions(tree),
    )


def _iter_source_modules(root: Path, source_roots: Iterable[str]) -> Iterable[Path]:
    for relative in source_roots:
        base = root / relative
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path


def _callee_name(node: ast.Call) -> str:
    function = node.func
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return ast.unparse(function)
    return ""


def _guard_calls(expression: ast.AST | None, guards: Mapping[str, GuardSpec]) -> list[ast.Call]:
    if expression is None:
        return []
    if isinstance(expression, ast.BoolOp):
        found: list[ast.Call] = []
        guaranteed = True
        for value in expression.values:
            if not guaranteed:
                break
            found.extend(_guard_calls(value, guards))
            if isinstance(value, ast.Constant):
                if isinstance(expression.op, ast.And) and not bool(value.value):
                    break
                if isinstance(expression.op, ast.Or) and bool(value.value):
                    break
            else:
                guaranteed = False
        return found
    if isinstance(expression, ast.IfExp):
        found = _guard_calls(expression.test, guards)
        if isinstance(expression.test, ast.Constant):
            branch = expression.body if bool(expression.test.value) else expression.orelse
            return [*found, *_guard_calls(branch, guards)]
        return [
            *found,
            *_guard_calls(expression.body, guards),
            *_guard_calls(expression.orelse, guards),
        ]
    found: list[ast.Call] = []
    if isinstance(expression, ast.Call) and _callee_name(expression) in guards:
        found.append(expression)
    for child in ast.iter_child_nodes(expression):
        found.extend(_guard_calls(child, guards))
    return found


def _evaluated_expressions(statement: ast.stmt) -> list[ast.AST]:
    """Return the expressions this statement evaluates before it transfers control."""

    if isinstance(statement, ast.If | ast.While):
        return [statement.test]
    if isinstance(statement, ast.For | ast.AsyncFor):
        return [statement.iter]
    if isinstance(statement, ast.Return):
        return [statement.value] if statement.value is not None else []
    if isinstance(statement, ast.Assign):
        return [statement.value]
    if isinstance(statement, ast.AnnAssign | ast.AugAssign):
        return [statement.value] if statement.value is not None else []
    if isinstance(statement, ast.Raise):
        return [node for node in (statement.exc, statement.cause) if node is not None]
    if isinstance(statement, ast.With | ast.AsyncWith):
        return [item.context_expr for item in statement.items]
    if isinstance(statement, ast.Expr):
        return [statement.value]
    if isinstance(statement, ast.Match):
        return [statement.subject]
    if isinstance(statement, ast.Assert):
        return [statement.test]
    return []


def _merge(left: bool | None, right: bool | None) -> bool | None:
    if left is None:
        return right
    if right is None:
        return left
    return left and right


class _DominanceAnalyzer:
    """Prove which exits of one declared decision function are admission-guarded."""

    def __init__(
        self,
        *,
        label: str,
        guards: Mapping[str, GuardSpec],
        used_names: frozenset[str],
        fail_closed_markers: Sequence[str],
    ) -> None:
        self._label = label
        self._guards = guards
        self._used_names = used_names
        self._fail_closed_markers = tuple(fail_closed_markers)
        self.used_markers: set[str] = set()

    def _branch_resolved(self, statements: Sequence[ast.stmt]) -> bool:
        """Report whether this branch either evaluates a guard or fails closed.

        An `if` chain that evaluates the admission on one branch and records a
        declared fail-closed reason on every other branch has resolved the
        admission for every path, so code after the chain is guarded.
        """

        findings: list[str] = []
        for statement in statements:
            if isinstance(statement, FunctionNode | ast.ClassDef):
                continue
            if self._live_guard(statement, findings):
                return True
            source = ast.unparse(statement)
            matched = [marker for marker in self._fail_closed_markers if marker in source]
            if matched:
                self.used_markers.update(matched)
                return True
            if isinstance(statement, ast.If):
                if not statement.orelse:
                    continue
                if self._branch_resolved(statement.body) and self._branch_resolved(
                    statement.orelse
                ):
                    return True
        return False

    def analyze(self, function: FunctionNode) -> BlockResult:
        result = self._block(function.body, False)
        if result.guarded is not None:
            result.exits.append(
                ExitRecord(
                    label="implicit-return",
                    expression="None",
                    guarded=bool(result.guarded),
                    line=function.end_lineno or function.lineno,
                )
            )
        return result

    def _live_guard(self, statement: ast.stmt, findings: list[str]) -> bool:
        """Report whether this statement really evaluates a guard for every path."""

        live = False
        for expression in _evaluated_expressions(statement):
            for call in _guard_calls(expression, self._guards):
                spec = self._guards[_callee_name(call)]
                if isinstance(statement, ast.Expr):
                    if spec.kind == "raises":
                        live = True
                    else:
                        findings.append(
                            f"{self._label}: line {call.lineno} discards the result of "
                            f"'{spec.name}', so it does not guard anything"
                        )
                    continue
                if isinstance(statement, ast.Assign):
                    targets = {
                        target.id for target in statement.targets if isinstance(target, ast.Name)
                    }
                    if targets and not (targets & self._used_names):
                        findings.append(
                            f"{self._label}: line {call.lineno} binds the result of "
                            f"'{spec.name}' to a name that is never read"
                        )
                        continue
                live = True
        return live

    def _block(self, statements: Sequence[ast.stmt], guarded: bool | None) -> BlockResult:
        exits: list[ExitRecord] = []
        findings: list[str] = []
        for statement in statements:
            if guarded is None:
                break
            if isinstance(statement, FunctionNode | ast.ClassDef):
                continue
            if self._live_guard(statement, findings):
                guarded = True
            if isinstance(statement, ast.Return):
                exits.append(
                    ExitRecord(
                        label="return",
                        expression=ast.unparse(statement.value) if statement.value else "None",
                        guarded=bool(guarded),
                        line=statement.lineno,
                    )
                )
                guarded = None
            elif isinstance(statement, ast.Raise):
                guarded = None
            elif isinstance(statement, ast.If):
                branch = self._block(statement.body, guarded)
                exits.extend(branch.exits)
                findings.extend(branch.findings)
                if statement.orelse:
                    alternative = self._block(statement.orelse, guarded)
                    exits.extend(alternative.exits)
                    findings.extend(alternative.findings)
                    guarded = _merge(branch.guarded, alternative.guarded)
                    if guarded is not None and self._branch_resolved([statement]):
                        guarded = True
                else:
                    guarded = _merge(branch.guarded, guarded)
            elif isinstance(statement, ast.While | ast.For | ast.AsyncFor):
                body = self._block(statement.body, guarded)
                exits.extend(body.exits)
                findings.extend(body.findings)
                if statement.orelse:
                    alternative = self._block(statement.orelse, guarded)
                    exits.extend(alternative.exits)
                    findings.extend(alternative.findings)
                elif _is_endless_loop(statement):
                    guarded = None
            elif isinstance(statement, ast.With | ast.AsyncWith):
                body = self._block(statement.body, guarded)
                exits.extend(body.exits)
                findings.extend(body.findings)
                guarded = body.guarded
            elif isinstance(statement, ast.Try | ast.TryStar):
                body = self._block(statement.body, guarded)
                exits.extend(body.exits)
                findings.extend(body.findings)
                outcome: bool | None = body.guarded
                if statement.orelse:
                    alternative = self._block(statement.orelse, body.guarded)
                    exits.extend(alternative.exits)
                    findings.extend(alternative.findings)
                    outcome = alternative.guarded
                for handler in statement.handlers:
                    # An exception can interrupt the body before a guard runs, so a
                    # handler starts from the state that entered the try block.
                    handled = self._block(handler.body, guarded)
                    exits.extend(handled.exits)
                    findings.extend(handled.findings)
                    outcome = _merge(outcome, handled.guarded)
                if statement.finalbody:
                    final = self._block(statement.finalbody, outcome)
                    exits.extend(final.exits)
                    findings.extend(final.findings)
                    outcome = final.guarded
                guarded = outcome
            elif isinstance(statement, ast.Match):
                matched: bool | None = None
                exhaustive = False
                for case in statement.cases:
                    if (
                        case.guard is None
                        and isinstance(case.pattern, ast.MatchAs)
                        and case.pattern.pattern is None
                    ):
                        exhaustive = True
                    branch = self._block(case.body, guarded)
                    exits.extend(branch.exits)
                    findings.extend(branch.findings)
                    matched = _merge(matched, branch.guarded)
                guarded = matched if exhaustive else _merge(matched, guarded)
        return BlockResult(guarded=guarded, exits=exits, findings=findings)


def _is_endless_loop(statement: ast.stmt) -> bool:
    """Report whether this loop can never fall through to the statement after it."""

    if not isinstance(statement, ast.While):
        return False
    test = statement.test
    if not (isinstance(test, ast.Constant) and bool(test.value)):
        return False
    for node in ast.walk(statement):
        if isinstance(node, ast.Break):
            return False
    return True


def _control_names(function: FunctionNode) -> frozenset[str]:
    """Return names whose values participate in a branch or returned decision."""

    expressions: list[ast.AST] = []
    for node in ast.walk(function):
        if isinstance(node, ast.If | ast.While | ast.Assert):
            expressions.append(node.test)
        elif isinstance(node, ast.Match):
            expressions.append(node.subject)
        elif isinstance(node, ast.Return) and node.value is not None:
            expressions.append(node.value)
    names = {
        node.id
        for expression in expressions
        for node in ast.walk(expression)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    changed = True
    while changed:
        changed = False
        for node in ast.walk(function):
            if isinstance(node, ast.Assign):
                targets = {target.id for target in node.targets if isinstance(target, ast.Name)}
                if targets & names:
                    dependencies = {
                        item.id
                        for item in ast.walk(node.value)
                        if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)
                    }
                    before = len(names)
                    names.update(dependencies)
                    changed = changed or len(names) != before
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in names
                and node.func.attr in {"append", "extend", "update"}
            ):
                dependencies = {
                    item.id
                    for argument in (*node.args, *(keyword.value for keyword in node.keywords))
                    for item in ast.walk(argument)
                    if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)
                }
                before = len(names)
                names.update(dependencies)
                changed = changed or len(names) != before
    return frozenset(names)


def _guard_specs(decision: Mapping[str, Any], label: str) -> tuple[dict[str, GuardSpec], list[str]]:
    errors: list[str] = []
    specs: dict[str, GuardSpec] = {}
    raw_guards = decision.get("guards")
    if not isinstance(raw_guards, list) or not raw_guards:
        errors.append(f"{label}: 'guards' must list at least one admission evaluation")
        return specs, errors
    for guard in raw_guards:
        if not isinstance(guard, dict):
            errors.append(f"{label}: every guard must be an object with 'name' and 'kind'")
            continue
        name = guard.get("name")
        kind = guard.get("kind")
        if not isinstance(name, str) or not name:
            errors.append(f"{label}: every guard needs a non-empty 'name'")
            continue
        if kind not in GUARD_KINDS:
            errors.append(f"{label}: guard '{name}' needs 'kind' of {sorted(GUARD_KINDS)}")
            continue
        specs[name] = GuardSpec(name=name, kind=kind)
    return specs, errors


def _guard_is_rooted(
    *,
    name: str,
    facts: ModuleFacts,
    assessor: str,
    assessor_module: str,
    rooted_imports: frozenset[str],
    visited: set[str],
) -> bool:
    """Report whether this callable really reaches the shared assessor.

    A guard is rooted when it is the shared assessor imported from the shared
    module, a helper imported from another registered boundary module, or a
    callable defined in this module that itself calls a rooted guard. A symbol
    with the right name imported from anywhere else is not rooted.
    """

    if name in visited:
        return False
    visited.add(name)
    if name == assessor:
        return facts.import_sources.get(name) == f"{assessor_module}.{assessor}"
    source = facts.import_sources.get(name)
    if source is not None:
        return source in rooted_imports
    local = name.removeprefix("self.")
    candidates = [
        qualified
        for qualified in facts.functions
        if qualified == local or qualified.rsplit(".", 1)[-1] == local
    ]
    for qualified in candidates:
        function = facts.functions[qualified]
        for node in ast.walk(function):
            if not isinstance(node, ast.Call):
                continue
            callee = _callee_name(node)
            if not callee:
                continue
            if _guard_is_rooted(
                name=callee,
                facts=facts,
                assessor=assessor,
                assessor_module=assessor_module,
                rooted_imports=rooted_imports,
                visited=visited,
            ):
                return True
    return False


def _validate_decisions(
    *,
    identifier: str,
    module_ref: str,
    boundary: Mapping[str, Any],
    facts: ModuleFacts,
    assessor: str,
    assessor_module: str,
    rooted_imports: frozenset[str],
    registered_decisions: frozenset[str],
) -> list[str]:
    errors: list[str] = []
    decisions = boundary.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        errors.append(f"{identifier}: 'decisions' must list at least one decision call site")
        return errors
    for decision in decisions:
        if not isinstance(decision, dict):
            errors.append(f"{identifier}: every decision must be an object")
            continue
        qualified = decision.get("function")
        if not isinstance(qualified, str) or not qualified:
            errors.append(f"{identifier}: every decision needs a 'function' qualified name")
            continue
        label = f"{identifier}: {module_ref}::{qualified}"
        function = facts.functions.get(qualified)
        if function is None:
            errors.append(f"{label} is not defined")
            continue
        guards, guard_errors = _guard_specs(decision, label)
        errors.extend(guard_errors)
        if not guards:
            continue
        for name in sorted(guards):
            if not _guard_is_rooted(
                name=name,
                facts=facts,
                assessor=assessor,
                assessor_module=assessor_module,
                rooted_imports=rooted_imports,
                visited=set(),
            ):
                errors.append(
                    f"{label}: guard '{name}' does not resolve to the shared assessor "
                    f"'{assessor}' from '{assessor_module}'"
                )
        markers = decision.get("fail_closed_markers", [])
        if not isinstance(markers, list) or not all(
            isinstance(marker, str) and marker for marker in markers
        ):
            errors.append(f"{label}: 'fail_closed_markers' must be a list of non-empty strings")
            markers = []
        analyzer = _DominanceAnalyzer(
            label=label,
            guards=guards,
            used_names=_control_names(function),
            fail_closed_markers=[str(marker) for marker in markers],
        )
        result = analyzer.analyze(function)
        errors.extend(result.findings)
        errors.extend(
            _classify_exits(
                label=label,
                decision=decision,
                exits=result.exits,
                registered_decisions=registered_decisions,
                markers_used_in_branches=frozenset(analyzer.used_markers),
            )
        )
    return errors


def _classify_exits(
    *,
    label: str,
    decision: Mapping[str, Any],
    exits: Sequence[ExitRecord],
    registered_decisions: frozenset[str],
    markers_used_in_branches: frozenset[str],
) -> list[str]:
    errors: list[str] = []
    fail_closed = decision.get("fail_closed_markers", [])
    if not isinstance(fail_closed, list) or not all(
        isinstance(marker, str) and marker for marker in fail_closed
    ):
        errors.append(f"{label}: 'fail_closed_markers' must be a list of non-empty strings")
        fail_closed = []
    delegations = decision.get("delegations", [])
    if not isinstance(delegations, list):
        errors.append(f"{label}: 'delegations' must be a list")
        delegations = []
    delegation_markers: list[tuple[str, str]] = []
    for delegation in delegations:
        if not isinstance(delegation, dict):
            errors.append(f"{label}: every delegation must be an object")
            continue
        marker = delegation.get("marker")
        target = delegation.get("decision")
        if not isinstance(marker, str) or not isinstance(target, str):
            errors.append(f"{label}: every delegation needs 'marker' and 'decision'")
            continue
        if target not in registered_decisions:
            errors.append(f"{label}: delegation target '{target}' is not a registered decision")
            continue
        delegation_markers.append((marker, target))
    used_fail_closed: set[str] = set(markers_used_in_branches)
    used_delegations: set[str] = set()
    for exit_record in exits:
        if exit_record.guarded:
            continue
        matched_fail_closed = [marker for marker in fail_closed if marker in exit_record.expression]
        if matched_fail_closed:
            used_fail_closed.update(matched_fail_closed)
            continue
        matched_delegation = [
            marker for marker, _ in delegation_markers if marker in exit_record.expression
        ]
        if matched_delegation:
            used_delegations.update(matched_delegation)
            continue
        errors.append(
            f"{label}: line {exit_record.line} returns "
            f"'{_shorten(exit_record.expression)}' without a dominating admission "
            "evaluation, and it is declared neither fail-closed nor delegated"
        )
    for marker in sorted(set(fail_closed) - used_fail_closed):
        errors.append(
            f"{label}: fail-closed marker '{marker}' no longer matches any unguarded exit"
        )
    for marker in sorted({marker for marker, _ in delegation_markers} - used_delegations):
        errors.append(f"{label}: delegation marker '{marker}' no longer matches any unguarded exit")
    return errors


def _shorten(expression: str, limit: int = 80) -> str:
    collapsed = " ".join(expression.split())
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[:limit]}..."


def _validate_schema(document: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    surface_digest = document.get("decision_surface_digest")
    if not isinstance(surface_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", surface_digest):
        errors.append("inventory: 'decision_surface_digest' must be a lowercase SHA-256 digest")
    shared = document.get("shared_admission")
    if not isinstance(shared, dict):
        raise InventoryError("inventory requires a 'shared_admission' object")
    for key in ("module", "assessor", "admission_type", "provider_protocol", "source"):
        if not isinstance(shared.get(key), str) or not shared[key]:
            raise InventoryError(f"inventory 'shared_admission.{key}' must be a non-empty string")
    boundaries = document.get("boundaries")
    if not isinstance(boundaries, list) or not boundaries:
        raise InventoryError("inventory requires a non-empty 'boundaries' array")
    identifiers: list[str] = []
    for index, boundary in enumerate(boundaries):
        label = f"boundaries[{index}]"
        if not isinstance(boundary, dict):
            raise InventoryError(f"{label} must be an object")
        missing = sorted(REQUIRED_BOUNDARY_KEYS - set(boundary))
        if missing:
            errors.append(f"{label}: missing required keys: {', '.join(missing)}")
            continue
        identifier = boundary["id"]
        if not isinstance(identifier, str) or not BOUNDARY_ID_PATTERN.match(identifier):
            errors.append(f"{label}: 'id' must be lowercase kebab-case")
            continue
        identifiers.append(identifier)
        tests = boundary["tests"]
        if not isinstance(tests, list) or not tests:
            errors.append(f"{identifier}: 'tests' must list at least one focused test file")
        constant = boundary["purpose_constant"]
        if constant is not None and not (
            isinstance(constant, str) and PURPOSE_CONSTANT_PATTERN.match(constant)
        ):
            errors.append(f"{identifier}: 'purpose_constant' must be null or a purpose constant")
        if (constant is None) != (boundary["purpose_id"] is None):
            errors.append(
                f"{identifier}: 'purpose_constant' and 'purpose_id' must both be set "
                "or both be null"
            )
        if constant is None and not boundary.get("purpose_note"):
            errors.append(
                f"{identifier}: a dynamic purpose requires a 'purpose_note' naming its source"
            )
    if len(set(identifiers)) != len(identifiers):
        errors.append("boundaries: 'id' values must be unique")
    if identifiers != sorted(identifiers):
        errors.append("boundaries: entries must be sorted by 'id'")
    return errors


def _registered_decisions(document: Mapping[str, Any]) -> frozenset[str]:
    registered: set[str] = set()
    for boundary in document["boundaries"]:
        if not isinstance(boundary, dict) or not isinstance(boundary.get("module"), str):
            continue
        for decision in boundary.get("decisions", []) or []:
            if isinstance(decision, dict) and isinstance(decision.get("function"), str):
                registered.add(f"{boundary['module']}::{decision['function']}")
    return frozenset(registered)


def _module_dotted_path(module_ref: str, source_roots: Sequence[str]) -> str:
    relative = module_ref
    for root in source_roots:
        prefix = f"{root.rstrip('/')}/"
        if relative.startswith(prefix):
            relative = relative[len(prefix) :]
            break
    package = Path(module_ref).parts
    if "fdai" in package:
        index = package.index("fdai")
        relative = "/".join(package[index:])
    return relative.removesuffix(".py").replace("/", ".")


def _validate_boundaries(
    *,
    root: Path,
    document: Mapping[str, Any],
    facts_by_module: dict[Path, ModuleFacts],
    assessor: str,
) -> list[str]:
    errors: list[str] = []
    source_roots = [str(entry) for entry in document.get("source_roots", [])]
    assessor_module = str(document["shared_admission"]["module"])
    rooted_imports = {
        f"{assessor_module}.{assessor}",
        *(
            f"{_module_dotted_path(str(boundary['module']), source_roots)}."
            f"{str(decision['function'])}"
            for boundary in document["boundaries"]
            if isinstance(boundary, dict) and isinstance(boundary.get("module"), str)
            for decision in boundary.get("decisions", [])
            if (
                isinstance(decision, dict)
                and isinstance(decision.get("function"), str)
                and "." not in str(decision["function"])
            )
        ),
    }
    for helper in document.get("admission_helpers", []):
        if not isinstance(helper, dict) or not isinstance(helper.get("module"), str):
            continue
        helper_module = _module_dotted_path(str(helper["module"]), source_roots)
        for function in helper.get("functions", []):
            if isinstance(function, str) and function:
                rooted_imports.add(f"{helper_module}.{function}")
    registered_decisions = _registered_decisions(document)
    for boundary in document["boundaries"]:
        if not isinstance(boundary, dict) or "id" not in boundary:
            continue
        identifier = boundary["id"]
        module_ref = boundary.get("module")
        if not isinstance(module_ref, str):
            errors.append(f"{identifier}: 'module' must be a repository-relative path")
            continue
        module_path = root / module_ref
        if not module_path.is_file():
            errors.append(f"{identifier}: module does not exist: {module_ref}")
            continue
        facts = facts_by_module.get(module_path)
        if facts is None:
            facts = _module_facts(module_path, assessor)
            facts_by_module[module_path] = facts
        if facts.imports_assessor and (
            facts.import_sources.get(assessor) != f"{assessor_module}.{assessor}"
        ):
            errors.append(
                f"{identifier}: {module_ref} imports '{assessor}' from "
                f"'{facts.import_sources.get(assessor)}' instead of '{assessor_module}'"
            )
        if _guards_assessor_directly(boundary, assessor):
            if not facts.imports_assessor:
                errors.append(
                    f"{identifier}: {module_ref} does not import the shared admission "
                    f"assessor '{assessor}'"
                )
            if not facts.calls_assessor:
                errors.append(
                    f"{identifier}: {module_ref} does not call the shared admission "
                    f"assessor '{assessor}'"
                )
            if not facts.fails_closed_on_absent_admission:
                errors.append(
                    f"{identifier}: {module_ref} does not fail closed on an absent admission"
                )
        constant = boundary.get("purpose_constant")
        if isinstance(constant, str):
            if constant not in facts.purpose_constants:
                errors.append(f"{identifier}: {module_ref} does not define {constant}")
            elif facts.purpose_constants[constant] != boundary.get("purpose_id"):
                errors.append(
                    f"{identifier}: {constant} is {facts.purpose_constants[constant]!r} in "
                    f"{module_ref} but the inventory declares {boundary.get('purpose_id')!r}"
                )
        for test_ref in boundary.get("tests", []):
            if not isinstance(test_ref, str) or not (root / test_ref).is_file():
                errors.append(f"{identifier}: focused test does not exist: {test_ref}")
        errors.extend(
            _validate_decisions(
                identifier=identifier,
                module_ref=module_ref,
                boundary=boundary,
                facts=facts,
                assessor=assessor,
                assessor_module=assessor_module,
                rooted_imports=frozenset(rooted_imports),
                registered_decisions=registered_decisions,
            )
        )
    return errors


def _guards_assessor_directly(boundary: Mapping[str, Any], assessor: str) -> bool:
    """Report whether any declared decision calls the shared assessor in this module."""

    for decision in boundary.get("decisions", []) or []:
        if not isinstance(decision, dict):
            continue
        for guard in decision.get("guards", []) or []:
            if isinstance(guard, dict) and guard.get("name") == assessor:
                return True
    return False


def _validate_completeness(
    *,
    root: Path,
    document: Mapping[str, Any],
    facts_by_module: dict[Path, ModuleFacts],
    assessor: str,
) -> list[str]:
    errors: list[str] = []
    assessor_module = str(document["shared_admission"]["module"])
    shared_source = root / str(document["shared_admission"]["source"])
    registered_modules = {
        root / boundary["module"]
        for boundary in document["boundaries"]
        if isinstance(boundary, dict) and isinstance(boundary.get("module"), str)
    }
    helper_modules: set[Path] = set()
    for helper in document.get("admission_helpers", []):
        if not isinstance(helper, dict) or not isinstance(helper.get("module"), str):
            errors.append("admission_helpers: every entry needs a 'module' path")
            continue
        if not helper.get("note"):
            errors.append(f"admission_helpers: {helper['module']} requires an explanatory 'note'")
        helper_path = root / helper["module"]
        if not helper_path.is_file():
            errors.append(f"admission_helpers: module does not exist: {helper['module']}")
            continue
        helper_modules.add(helper_path)
    declared_constants: dict[Path, set[str]] = {}
    for boundary in document["boundaries"]:
        if not isinstance(boundary, dict) or not isinstance(boundary.get("module"), str):
            continue
        constant = boundary.get("purpose_constant")
        if isinstance(constant, str):
            declared_constants.setdefault(root / boundary["module"], set()).add(constant)
    for declaration in document.get("purpose_declarations", []):
        if not isinstance(declaration, dict):
            errors.append("purpose_declarations: every entry must be an object")
            continue
        module_ref = declaration.get("module")
        constant = declaration.get("constant")
        if not isinstance(module_ref, str) or not isinstance(constant, str):
            errors.append("purpose_declarations: every entry needs 'module' and 'constant'")
            continue
        if not declaration.get("note"):
            errors.append(f"purpose_declarations: {constant} requires an explanatory 'note'")
        declared_constants.setdefault(root / module_ref, set()).add(constant)
    source_roots = document.get("source_roots")
    if not isinstance(source_roots, list) or not source_roots:
        raise InventoryError("inventory requires a non-empty 'source_roots' array")
    for module_path in _iter_source_modules(root, source_roots):
        if module_path == shared_source:
            continue
        facts = facts_by_module.get(module_path)
        if facts is None:
            facts = _module_facts(module_path, assessor)
            facts_by_module[module_path] = facts
        relative = module_path.relative_to(root).as_posix()
        if facts.calls_assessor and module_path not in registered_modules:
            if module_path in helper_modules:
                # A declared helper computes a verdict for a registered boundary, so it
                # still has to reach the shared assessor through the shared module.
                if facts.import_sources.get(assessor) != f"{assessor_module}.{assessor}":
                    errors.append(
                        f"{relative} imports '{assessor}' from "
                        f"'{facts.import_sources.get(assessor)}' instead of '{assessor_module}'"
                    )
            else:
                errors.append(
                    f"{relative} resolves the shared admission but is not a registered boundary"
                )
        known = declared_constants.get(module_path, set())
        for constant in sorted(set(facts.purpose_constants) - known):
            errors.append(
                f"{relative} declares {constant} but the inventory registers neither a "
                "boundary nor a purpose declaration for it"
            )
    return errors


def _validate_negative_matrix(root: Path, document: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    matrix = document.get("negative_evidence_matrix")
    if not isinstance(matrix, dict):
        errors.append("inventory requires a 'negative_evidence_matrix' object")
        return errors
    classes = matrix.get("classes")
    if not isinstance(classes, list) or tuple(classes) != REQUIRED_NEGATIVE_CLASSES:
        errors.append(
            "negative_evidence_matrix.classes must be exactly: "
            + ", ".join(REQUIRED_NEGATIVE_CLASSES)
        )
    tests = matrix.get("tests")
    if not isinstance(tests, list) or not tests:
        errors.append("negative_evidence_matrix.tests must list at least one focused test file")
        return errors
    for test_ref in tests:
        path = root / str(test_ref)
        if not path.is_file():
            errors.append(f"negative_evidence_matrix: test does not exist: {test_ref}")
            continue
        text = path.read_text(encoding="utf-8")
        for negative_class in REQUIRED_NEGATIVE_CLASSES:
            if negative_class not in text:
                errors.append(
                    f"negative_evidence_matrix: {test_ref} does not cover the "
                    f"'{negative_class}' evidence class"
                )
    return errors


def validate(*, root: Path, inventory_path: Path) -> list[str]:
    document = _load_inventory(inventory_path)
    errors = _validate_schema(document)
    expected_surface_digest = document.get("decision_surface_digest")
    actual_surface_digest = _decision_surface_digest(root, document)
    if expected_surface_digest != actual_surface_digest:
        errors.append(
            "inventory: decision_surface_digest does not match the registered decision surface "
            f"(expected {expected_surface_digest!r}, actual {actual_surface_digest})"
        )
    shared = document["shared_admission"]
    assessor = str(shared["assessor"])
    admission_type = str(shared["admission_type"])
    shared_source = root / str(shared["source"])
    if not shared_source.is_file():
        errors.append(f"shared_admission.source does not exist: {shared['source']}")
        return errors
    shared_text = shared_source.read_text(encoding="utf-8")
    for symbol in (assessor, admission_type, str(shared["provider_protocol"])):
        if symbol not in shared_text:
            errors.append(f"shared_admission: {shared['source']} does not define {symbol}")
    facts_by_module: dict[Path, ModuleFacts] = {}
    errors.extend(
        _validate_boundaries(
            root=root,
            document=document,
            facts_by_module=facts_by_module,
            assessor=assessor,
        )
    )
    errors.extend(
        _validate_completeness(
            root=root,
            document=document,
            facts_by_module=facts_by_module,
            assessor=assessor,
        )
    )
    errors.extend(_validate_negative_matrix(root, document))
    return errors


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--inventory", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    root = arguments.root.resolve()
    inventory_path = arguments.inventory or (root / DEFAULT_INVENTORY)
    try:
        errors = validate(root=root, inventory_path=inventory_path)
    except InventoryError as error:
        print(f"decision-boundary-coverage: ERROR: {error}", file=sys.stderr)
        return 1
    if errors:
        for message in errors:
            print(f"decision-boundary-coverage: ERROR: {message}", file=sys.stderr)
        return 1
    print("decision-boundary-coverage: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
