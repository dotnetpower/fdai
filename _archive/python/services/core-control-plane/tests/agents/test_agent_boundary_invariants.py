from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
AGENTS = REPO_ROOT / "services/core-control-plane/src/fdai/agents"
FRAMEWORK = AGENTS / "_framework"

HUGINN_SOURCES = (AGENTS / "huginn.py", FRAMEWORK / "huginn_dedup.py")
NO_SYNC_LLM_SOURCES = (
    AGENTS / "huginn.py",
    FRAMEWORK / "huginn_dedup.py",
    AGENTS / "heimdall.py",
    FRAMEWORK / "heimdall_action_observation.py",
    FRAMEWORK / "heimdall_alert_window.py",
    FRAMEWORK / "heimdall_forecast.py",
    FRAMEWORK / "heimdall_helpers.py",
    FRAMEWORK / "heimdall_huginn_projection.py",
    FRAMEWORK / "heimdall_provider_schema.py",
    FRAMEWORK / "heimdall_retrieval_validation.py",
    AGENTS / "njord.py",
    AGENTS / "freyr.py",
    AGENTS / "loki.py",
    FRAMEWORK / "loki_reservations.py",
    FRAMEWORK / "loki_resilience.py",
)
SPECIALIST_SOURCES = (AGENTS / "njord.py", AGENTS / "freyr.py", AGENTS / "loki.py")
NORNS_SOURCES = (
    AGENTS / "norns.py",
    FRAMEWORK / "norns_candidate_delivery.py",
    FRAMEWORK / "norns_case_history.py",
    FRAMEWORK / "norns_consensus.py",
    FRAMEWORK / "norns_deployment_learning.py",
    FRAMEWORK / "norns_issue_dedup.py",
    FRAMEWORK / "norns_learning.py",
    FRAMEWORK / "norns_semantic_feedback.py",
)
PANTHEON_SOURCE = AGENTS / "_framework/pantheon.py"

CLOUD_SDK_ROOTS = frozenset({"azure", "boto3", "botocore", "kubernetes"})
CLOUD_SDK_PREFIXES = ("google.cloud",)
INVENTORY_WRITE_MODULES = frozenset(
    {
        "asyncpg",
        "psycopg",
        "psycopg2",
        "sqlalchemy",
        "fdai.delivery.inventory_collection",
        "fdai.delivery.inventory_sync",
        "fdai.delivery.inventory_sync_cli",
        "fdai.delivery.persistence.inventory",
        "fdai.core.ontology_platform.inventory_projector",
    }
)
LLM_MODULE_SEGMENTS = frozenset({"llm", "openai", "anthropic"})
LLM_SYMBOLS = frozenset(
    {
        "AzureOpenAI",
        "ChatCompletion",
        "Completion",
        "CrossCheckModel",
        "LlmBindings",
        "T2Synthesizer",
    }
)
LLM_CALLS = frozenset({"chat", "complete", "acomplete", "generate", "invoke", "synthesize"})
EXECUTOR_MODULE_SEGMENTS = frozenset({"executor", "thor", "rollback_executor"})
EXECUTOR_SYMBOLS = frozenset({"ActionExecutor", "RollbackExecutor", "Thor"})
CATALOG_WRITER_SYMBOLS = frozenset({"CatalogReviewPublisher", "Mimir", "RuleCatalogWriter"})


def test_huginn_has_no_cloud_sdk_or_inventory_database_writes() -> None:
    violations = _huginn_boundary_violations(_read_sources(HUGINN_SOURCES))

    assert violations == []
    assert _huginn_boundary_violations(
        {"bad_huginn.py": "from azure.mgmt.resource import ResourceManagementClient\n"}
    )
    assert _huginn_boundary_violations({"bad_huginn_db.py": "import psycopg\n"})


def test_sensing_and_specialists_have_no_synchronous_llm_calls() -> None:
    violations = _llm_boundary_violations(_read_sources(NO_SYNC_LLM_SOURCES))

    assert violations == []
    assert _llm_boundary_violations(
        {"bad_llm.py": "from fdai.shared.providers.llm import LlmBindings\n"}
    )
    assert _llm_boundary_violations({"bad_call.py": "def handle(llm):\n    llm.complete('x')\n"})


def test_domain_specialists_never_import_execute_or_publish_action_records() -> None:
    violations = _specialist_execution_violations(_read_sources(SPECIALIST_SOURCES))
    violations.extend(_specialist_executes_violations(PANTHEON_SOURCE.read_text()))

    assert violations == []
    assert _specialist_execution_violations(
        {"bad_specialist.py": "from fdai.agents.thor import Thor\n"}
    )
    assert _specialist_execution_violations(
        {
            "bad_publish.py": (
                "async def handle(bus):\n    await bus.publish('Loki', 'object.action-run', {})\n"
            )
        }
    )
    assert _specialist_executes_violations(
        "_NJORD = AgentSpec(name='Njord', executes=('ops.mutate',))\n"
    )


def test_norns_never_writes_catalog_or_publishes_rule_policy_topics() -> None:
    violations = _norns_catalog_mutation_violations(_read_sources(NORNS_SOURCES))

    assert violations == []
    assert _norns_catalog_mutation_violations(
        {"bad_norns.py": "from fdai.agents.mimir import Mimir\n"}
    )
    assert _norns_catalog_mutation_violations(
        {
            "bad_publish.py": (
                "async def handle(bus):\n    await bus.publish('Norns', 'object.rule', {})\n"
            )
        }
    )


def test_only_thor_typed_port_dispatches_verdicts_in_production_source() -> None:
    callers = _dispatch_verdict_callers(_production_sources_mentioning("dispatch_verdict"))

    assert callers == [("services/core-control-plane/src/fdai/agents/thor.py", "on_typed_message")]
    assert _dispatch_verdict_callers(
        {"bad_direct.py": "async def bypass(thor):\n    await thor.dispatch_verdict({})\n"}
    ) == [("bad_direct.py", "bypass")]


def _production_sources_mentioning(needle: str) -> dict[str, str]:
    sources: dict[str, str] = {}
    for root in ("services", "packages", "extensions"):
        for path in sorted((REPO_ROOT / root).glob("*/src/**/*.py")):
            text = path.read_text(encoding="utf-8")
            if needle in text:
                sources[str(path.relative_to(REPO_ROOT))] = text
    return sources


def _dispatch_verdict_callers(sources: dict[str, str]) -> list[tuple[str, str]]:
    callers: list[tuple[str, str]] = []
    for name, source in sources.items():
        tree = ast.parse(source, filename=name)
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for node in ast.walk(function):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "dispatch_verdict"
                ):
                    callers.append((name, function.name))
    return sorted(set(callers))


def _read_sources(paths: tuple[Path, ...]) -> dict[str, str]:
    return {str(path.relative_to(REPO_ROOT)): path.read_text() for path in paths}


def _imports(tree: ast.AST) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((alias.name, alias.asname or alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            found.extend((module, alias.name) for alias in node.names)
    return found


def _huginn_boundary_violations(sources: dict[str, str]) -> list[str]:
    violations: list[str] = []
    for filename, source in sources.items():
        tree = ast.parse(source, filename=filename)
        for module, _name in _imports(tree):
            root = module.split(".", 1)[0]
            if (
                root in CLOUD_SDK_ROOTS
                or module.startswith(CLOUD_SDK_PREFIXES)
                or module in INVENTORY_WRITE_MODULES
            ):
                violations.append(f"{filename}: forbidden import {module}")
    return violations


def _llm_boundary_violations(sources: dict[str, str]) -> list[str]:
    violations: list[str] = []
    for filename, source in sources.items():
        tree = ast.parse(source, filename=filename)
        for module, name in _imports(tree):
            if any(segment in module.split(".") for segment in LLM_MODULE_SEGMENTS):
                violations.append(f"{filename}: forbidden model import {module}")
            if name in LLM_SYMBOLS:
                violations.append(f"{filename}: forbidden model symbol {name}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                base = _root_name(node.func.value)
                if (
                    node.func.attr in LLM_CALLS
                    and base is not None
                    and any(token in base.lower() for token in ("llm", "model", "synthesizer"))
                ):
                    violations.append(f"{filename}: forbidden model call {base}.{node.func.attr}")
    return violations


def _specialist_execution_violations(sources: dict[str, str]) -> list[str]:
    violations: list[str] = []
    for filename, source in sources.items():
        tree = ast.parse(source, filename=filename)
        for module, name in _imports(tree):
            if any(segment in module.split(".") for segment in EXECUTOR_MODULE_SEGMENTS):
                violations.append(f"{filename}: forbidden executor import {module}")
            if name in EXECUTOR_SYMBOLS:
                violations.append(f"{filename}: forbidden executor symbol {name}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in EXECUTOR_SYMBOLS:
                violations.append(f"{filename}: forbidden executor reference {node.id}")
            if _publishes_forbidden_topic(node, {"object.action-run", "object.rollback"}):
                violations.append(f"{filename}: forbidden action topic publish")
    return violations


def _specialist_executes_violations(source: str) -> list[str]:
    tree = ast.parse(source)
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node.func) != "AgentSpec":
            continue
        name = _keyword_constant(node, "name")
        if name not in {"Njord", "Freyr", "Loki"}:
            continue
        executes = _keyword(node, "executes")
        if executes is not None and not _empty_sequence(executes):
            violations.append(f"{name}: non-empty executes")
    return violations


def _norns_catalog_mutation_violations(sources: dict[str, str]) -> list[str]:
    violations: list[str] = []
    for filename, source in sources.items():
        tree = ast.parse(source, filename=filename)
        for module, name in _imports(tree):
            if module == "fdai.agents.mimir" or name in CATALOG_WRITER_SYMBOLS:
                violations.append(f"{filename}: forbidden catalog writer import {module}.{name}")
            if module.startswith("fdai.rule_catalog") and module.split(".")[-1] in {
                "writer",
                "writers",
                "publisher",
                "promotion",
            }:
                violations.append(f"{filename}: forbidden catalog mutation import {module}")
        for node in ast.walk(tree):
            if _publishes_forbidden_topic(node, {"object.rule", "object.policy"}):
                violations.append(f"{filename}: forbidden catalog topic publish")
    return violations


def _publishes_forbidden_topic(node: ast.AST, topics: set[str]) -> bool:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr != "publish" or len(node.args) < 2:
        return False
    topic = node.args[1]
    return isinstance(topic, ast.Constant) and topic.value in topics


def _root_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _root_name(node.value)
    return None


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _keyword(node: ast.Call, name: str) -> ast.AST | None:
    return next((keyword.value for keyword in node.keywords if keyword.arg == name), None)


def _keyword_constant(node: ast.Call, name: str) -> object:
    value = _keyword(node, name)
    return value.value if isinstance(value, ast.Constant) else None


def _empty_sequence(node: ast.AST) -> bool:
    return isinstance(node, ast.Tuple | ast.List) and not node.elts
