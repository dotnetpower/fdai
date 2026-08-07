"""Executable Operator API structure and default-route baselines.

The G-5 split in #19 established the first package boundary. Issue #67
records the current package and wire shape before the next architecture
evolution so namespace moves can be distinguished from behavior changes.
"""

from __future__ import annotations

import ast
import fnmatch
import importlib.util
import json
from pathlib import Path

from starlette.testclient import TestClient

_REPO_ROOT = Path(__file__).resolve().parents[3]
_OPERATOR_API_DIR = _REPO_ROOT / "src" / "fdai" / "delivery" / "operator_api"
_MODULE_INVENTORY_PATH = (
    _REPO_ROOT / "docs" / "roadmap" / "interfaces" / "operator-console-module-inventory.json"
)

_REQUIRED_SUBPACKAGES = frozenset(
    {
        "adapters",
        "app",
        "application",
        "dev",
        "persistence",
        "production",
        "routes",
        "streaming",
    }
)

_PACKAGE_CLASSIFICATIONS = frozenset(
    {
        "application-coordination",
        "composition",
        "mixed-transitional",
        "provider-adapter",
        "public-or-transitional",
        "read-projection",
        "stream-transport",
        "test-fixture",
    }
)
_TOP_LEVEL_CLASSIFICATIONS = frozenset(
    {
        "delivery-coordination",
        "public-facade",
        "read-model",
        "transitional-cross-service",
    }
)
_ROUTE_CLASSIFICATIONS = frozenset(
    {
        "compatibility-shim",
        "internal-transitional",
        "mixed-domain-route",
        "mixed-transitional",
        "read-projection",
    }
)
_IMPORT_SURFACE_CLASSIFICATIONS = frozenset(
    {
        "internal-implementation",
        "public-delivery-contract",
        "public-deployment-entrypoint",
        "public-facade",
        "public-compatibility-facade",
        "shared-delivery-contract",
        "test-and-local-only",
        "test-only-compatibility-debt",
        "transitional-cross-service",
        "transitional-public-reexport",
        "transitional-public-extension-seam",
    }
)

_INVENTORY_KEYS = frozenset(
    {
        "schema_version",
        "owner",
        "tracking_issue",
        "scope",
        "packages",
        "migration_selections",
        "top_level_modules",
        "route_families",
        "reviewed_fallback_modules",
        "import_surfaces",
        "wire_baselines",
        "client_wire_baselines",
        "known_wire_debts",
    }
)
_PACKAGE_KEYS = frozenset({"path", "responsibility", "classification", "candidate_destination"})
_MODULE_RULE_KEYS = frozenset({"pattern", "responsibility", "classification"})
_ROUTE_RULE_KEYS = _MODULE_RULE_KEYS | {"candidate_destination"}
_IMPORT_SURFACE_REQUIRED_KEYS = frozenset({"module", "classification", "migration"})
_IMPORT_SURFACE_KEYS = _IMPORT_SURFACE_REQUIRED_KEYS | {"consumer_scope"}
_WIRE_BASELINE_KEYS = frozenset({"contract", "test"})
_CLIENT_WIRE_BASELINE_KEYS = frozenset({"contract", "test_file", "test_name"})
_KNOWN_WIRE_DEBT_KEYS = frozenset({"contract", "tracking_issue", "exit_condition"})
_MIGRATION_SELECTION_KEYS = frozenset(
    {
        "tracking_issue",
        "family",
        "destination",
        "observed_window_days",
        "modules",
        "rationale",
        "rollback",
    }
)
_MIGRATION_MODULE_KEYS = frozenset({"module", "direct_python_consumers", "fdai_imports", "changes"})

_DEFAULT_ROUTE_SNAPSHOT = (
    (("GET", "HEAD"), "/audit", "get_audit"),
    (("GET", "HEAD"), "/audit/{correlation_id}/trace", "rule_fire_trace"),
    (("GET", "HEAD"), "/healthz", "healthz"),
    (("GET", "HEAD"), "/hil-queue", "get_hil_queue"),
    (("GET", "HEAD"), "/incidents", "panel:incidents"),
    (("GET", "HEAD"), "/incidents/stream", "incident_attention_stream"),
    (("GET", "HEAD"), "/kpi", "get_kpi"),
    (
        ("GET", "HEAD"),
        "/notification-templates/incident-opened",
        "get_incident_opened_template",
    ),
    (("GET", "HEAD"), "/rca", "panel:rca"),
    (("GET", "HEAD"), "/system/data-sources", "get_data_sources"),
)

# Files that legitimately live at the top level (not under a subpackage).
# Foundational Operator API contracts + concrete composition-root entrypoints
# only. Route handlers, SSE emitters, and dev harnesses stay in their
# subpackages; the concrete `PostgresConsoleReadModel` is the natural
# sibling of `read_model.py` (the Protocol it implements) and `prod.py`
# is the production counterpart to `dev/local.py`.
_TOP_LEVEL_ALLOWED = frozenset(
    {
        "__init__.py",
        "main.py",
        "auth.py",
        "console_action_dispatch.py",
        "console_action_dispatch_models.py",
        "console_action_dispatch_store.py",
        "console_incident_ticket.py",
        "entra_verifier.py",
        "read_model.py",
        "postgres_read_model.py",
        "prod.py",
    }
)


# ---------------------------------------------------------------------------
# H1: layout drift - top-level *.py MUST be exactly the allowed set.
# ---------------------------------------------------------------------------


def test_top_level_operator_api_is_only_allowed_files() -> None:
    top_pyfiles = {p.name for p in _OPERATOR_API_DIR.glob("*.py")}
    assert top_pyfiles == _TOP_LEVEL_ALLOWED, (
        "Top-level operator_api/*.py must match the issue #67 baseline. "
        f"Unexpected: {sorted(top_pyfiles - _TOP_LEVEL_ALLOWED)}; "
        f"missing: {sorted(_TOP_LEVEL_ALLOWED - top_pyfiles)}."
    )


def test_required_subpackages_exist() -> None:
    for name in _REQUIRED_SUBPACKAGES:
        sub = _OPERATOR_API_DIR / name
        assert sub.is_dir(), f"operator_api/{name}/ sub-package missing"
        assert (sub / "__init__.py").is_file(), f"operator_api/{name}/__init__.py missing"


def test_module_inventory_covers_current_operator_api_tree() -> None:
    inventory = json.loads(_MODULE_INVENTORY_PATH.read_text(encoding="utf-8"))
    assert set(inventory) == _INVENTORY_KEYS
    assert inventory["schema_version"] == "1.0.0"
    assert inventory["tracking_issue"] == 67
    assert inventory["scope"] == "src/fdai/delivery/operator_api"
    assert inventory["owner"].strip()

    package_entries = inventory["packages"]
    assert all(set(entry) == _PACKAGE_KEYS for entry in package_entries)
    package_paths = {entry["path"] for entry in package_entries}
    actual_module_directories = {
        path.parent.relative_to(_OPERATOR_API_DIR).as_posix()
        for path in _OPERATOR_API_DIR.rglob("*.py")
    }

    assert package_paths == actual_module_directories
    for entry in package_entries:
        assert entry["responsibility"].strip()
        assert entry["classification"] in _PACKAGE_CLASSIFICATIONS
        assert entry["candidate_destination"].strip()

    top_level_modules = {path.name for path in _OPERATOR_API_DIR.glob("*.py")}
    top_level_rules = inventory["top_level_modules"]
    assert all(set(entry) == _MODULE_RULE_KEYS for entry in top_level_rules)
    assert all(entry["classification"] in _TOP_LEVEL_CLASSIFICATIONS for entry in top_level_rules)
    assert all(entry["responsibility"].strip() for entry in top_level_rules)
    top_level_matches = {
        module: [
            rule["pattern"]
            for rule in top_level_rules
            if any(fnmatch.fnmatchcase(module, pattern) for pattern in rule["pattern"].split("|"))
        ]
        for module in top_level_modules
    }
    assert all(len(matches) == 1 for matches in top_level_matches.values())

    route_rules = inventory["route_families"]
    assert all(set(entry) == _ROUTE_RULE_KEYS for entry in route_rules)
    assert all(entry["classification"] in _ROUTE_CLASSIFICATIONS for entry in route_rules)
    assert all(entry["responsibility"].strip() for entry in route_rules)
    assert all(entry["candidate_destination"].strip() for entry in route_rules)
    assert route_rules[-1]["pattern"] == "*.py"
    specific_rules = route_rules[:-1]
    route_modules = {
        path.name
        for path in (_OPERATOR_API_DIR / "routes").glob("*.py")
        if path.name != "__init__.py"
    }
    specific_matches = {
        module: [
            rule["pattern"]
            for rule in specific_rules
            if fnmatch.fnmatchcase(module, rule["pattern"])
        ]
        for module in route_modules
    }
    overlapping = {
        module: matches for module, matches in specific_matches.items() if len(matches) > 1
    }
    fallback_modules = {module for module, matches in specific_matches.items() if not matches}

    assert not overlapping
    assert fallback_modules == set(inventory["reviewed_fallback_modules"])
    uncovered = {
        module
        for module in route_modules
        if not any(fnmatch.fnmatchcase(module, rule["pattern"]) for rule in route_rules)
    }

    assert not uncovered
    import_surface_keys = {
        (entry["module"], entry.get("consumer_scope")) for entry in inventory["import_surfaces"]
    }
    assert len(import_surface_keys) == len(inventory["import_surfaces"])
    required_boundary_surfaces = {
        "fdai.delivery.auth",
        "fdai.delivery.agent_activity",
        "fdai.delivery.operator_api.auth",
        "fdai.delivery.operator_api.entra_verifier",
        "fdai.delivery.operator_api.streaming.agent_runtime_state_publisher",
    }
    assert required_boundary_surfaces <= {entry["module"] for entry in inventory["import_surfaces"]}
    assert all(
        _IMPORT_SURFACE_REQUIRED_KEYS <= set(entry) <= _IMPORT_SURFACE_KEYS
        for entry in inventory["import_surfaces"]
    )
    assert all(
        entry["classification"] in _IMPORT_SURFACE_CLASSIFICATIONS
        for entry in inventory["import_surfaces"]
    )
    assert all(entry["migration"].strip() for entry in inventory["import_surfaces"])
    for entry in inventory["import_surfaces"]:
        module = entry["module"]
        if module.endswith(".*"):
            package_path = _REPO_ROOT / "src" / Path(*module.removesuffix(".*").split("."))
            assert package_path.is_dir() and any(package_path.glob("*.py")), (
                f"wildcard import surface has no modules: {module}"
            )
        else:
            assert importlib.util.find_spec(module) is not None, (
                f"import surface module missing: {module}"
            )
    wire_baselines = inventory["wire_baselines"]
    assert all(set(entry) == _WIRE_BASELINE_KEYS for entry in wire_baselines)
    assert len({entry["contract"] for entry in wire_baselines}) == len(wire_baselines)
    assert len({entry["test"] for entry in wire_baselines}) == len(wire_baselines)
    for entry in wire_baselines:
        test_path, separator, node_id = entry["test"].partition("::")
        assert separator and node_id
        node_names = node_id.split("::")
        assert node_names[-1].startswith("test_")
        assert all(name.startswith("Test") for name in node_names[:-1])
        path = _REPO_ROOT / test_path
        assert path.is_file(), f"wire baseline test missing: {test_path}"
        body = ast.parse(path.read_text(encoding="utf-8")).body
        for node_name in node_names:
            node = next(
                (
                    candidate
                    for candidate in body
                    if isinstance(candidate, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                    and candidate.name == node_name
                ),
                None,
            )
            assert node is not None, f"wire baseline node missing: {entry['test']}"
            decorator_names = {
                ast.unparse(decorator) for decorator in getattr(node, "decorator_list", ())
            }
            assert not any("skip" in name or "xfail" in name for name in decorator_names), (
                f"wire baseline node cannot be skipped or xfailed: {entry['test']}"
            )
            body = node.body if isinstance(node, ast.ClassDef) else []

    client_wire_baselines = inventory["client_wire_baselines"]
    assert all(set(entry) == _CLIENT_WIRE_BASELINE_KEYS for entry in client_wire_baselines)
    assert len({entry["contract"] for entry in client_wire_baselines}) == len(client_wire_baselines)
    assert len({entry["test_file"] for entry in client_wire_baselines}) == len(
        client_wire_baselines
    )
    for entry in client_wire_baselines:
        path = _REPO_ROOT / entry["test_file"]
        assert path.is_file(), f"client wire baseline test missing: {entry['test_file']}"
        source = path.read_text(encoding="utf-8")
        assert f'test("{entry["test_name"]}"' in source, (
            f"client wire baseline test name missing: {entry['test_file']}::{entry['test_name']}"
        )

    known_wire_debts = inventory["known_wire_debts"]
    assert all(set(entry) == _KNOWN_WIRE_DEBT_KEYS for entry in known_wire_debts)
    assert len({entry["contract"] for entry in known_wire_debts}) == len(known_wire_debts)
    assert all(entry["tracking_issue"] > inventory["tracking_issue"] for entry in known_wire_debts)
    assert all(entry["exit_condition"].strip() for entry in known_wire_debts)

    selections = inventory["migration_selections"]
    assert len(selections) == 8
    assert all(set(selection) == _MIGRATION_SELECTION_KEYS for selection in selections)
    selections_by_family = {selection["family"]: selection for selection in selections}
    assert set(selections_by_family) == {
        "audit*.py",
        "chat_inventory*.py",
        "chat_evidence*.py",
        "chat_presentation*.py",
        "chat terminal projections",
        "chat terminal support projections",
        "chat conversation lifecycle",
        "chat application capabilities",
    }
    expected = {
        "audit*.py": (
            70,
            "fdai.delivery.operator_api.projections.audit",
            {
                "audit_finops.py",
                "audit_measurement_events.py",
                "audit_measurement_projection.py",
                "audit_measurement_summary.py",
                "audit_query.py",
            },
        ),
        "chat_presentation*.py": (
            71,
            "fdai.delivery.operator_api.projections.conversation.presentation",
            {
                "chat_presentation.py",
                "chat_presentation_artifact.py",
                "chat_presentation_artifact_common.py",
                "chat_presentation_contract.py",
                "chat_presentation_health_artifact.py",
                "chat_presentation_inventory_artifact.py",
                "chat_presentation_profiles.py",
            },
        ),
        "chat_inventory*.py": (
            71,
            (
                "fdai.delivery.operator_api.application.conversation.capabilities.inventory "
                "and fdai.delivery.operator_api.projections.conversation.inventory"
            ),
            {
                "chat_inventory.py",
                "chat_inventory_activity.py",
                "chat_inventory_compiler.py",
                "chat_inventory_followup.py",
                "chat_inventory_language.py",
                "chat_inventory_ontology.py",
                "chat_inventory_projection.py",
                "chat_inventory_query.py",
                "chat_inventory_rendering.py",
                "chat_inventory_resource_types.py",
                "chat_inventory_schedule.py",
                "chat_inventory_semantic_retrieval.py",
                "chat_inventory_semantics.py",
            },
        ),
        "chat_evidence*.py": (
            71,
            "fdai.delivery.operator_api.application.conversation.evidence",
            {
                "chat_evidence.py",
                "chat_evidence_branches.py",
                "chat_evidence_enrichment.py",
                "chat_evidence_pipeline.py",
                "chat_evidence_provenance.py",
            },
        ),
        "chat terminal projections": (
            71,
            "fdai.delivery.operator_api.projections.conversation.terminal",
            {
                "chat_stream_terminal.py",
                "chat_llm_usage_rendering.py",
                "chat_resource_result_context.py",
                "chat_source_failure_context.py",
            },
        ),
        "chat terminal support projections": (
            71,
            "fdai.delivery.operator_api.projections.conversation",
            {
                "chat_trajectory_detail.py",
                "chat_screen_data.py",
                "chat_model_trace.py",
                "chat_resource_context.py",
            },
        ),
        "chat conversation lifecycle": (
            71,
            (
                "fdai.delivery.operator_api.application.conversation.planning, "
                "fdai.delivery.operator_api.application.conversation.post_generation, "
                "fdai.delivery.operator_api.application.conversation.request_preparation, "
                "and fdai.delivery.operator_api.application.conversation.busy_input"
            ),
            {
                "chat_answer_planning.py",
                "chat_answer_quality.py",
                "chat_content_policy.py",
                "chat_busy_input.py",
            },
        ),
        "chat application capabilities": (
            71,
            (
                "fdai.delivery.operator_api.application.conversation, "
                "fdai.delivery.operator_api.application.conversation.capabilities, "
                "and fdai.delivery.operator_api.adapters.conversation.web_search"
            ),
            {
                "chat_agent_delegate.py",
                "chat_skills.py",
                "chat_configuration_drift.py",
                "chat_web_search.py",
                "chat_capability_registry.py",
                "chat_topology_intent.py",
            },
        ),
    }
    for family, (tracking_issue, destination, expected_modules) in expected.items():
        selection = selections_by_family[family]
        assert selection["tracking_issue"] == tracking_issue
        assert selection["destination"] == destination
        assert selection["observed_window_days"] == 90
        assert selection["rationale"].strip()
        assert selection["rollback"].strip()
        modules = selection["modules"]
        assert all(set(entry) == _MIGRATION_MODULE_KEYS for entry in modules)
        assert {entry["module"] for entry in modules} == expected_modules
        assert all(entry["direct_python_consumers"] >= 0 for entry in modules)
        assert all(entry["fdai_imports"] >= 0 for entry in modules)
        assert all(entry["changes"] >= 1 for entry in modules)


# ---------------------------------------------------------------------------
# H2: URL/route shape stability. build_app() succeeds and produces a
# non-empty starlette Router. A regression that broke composition would
# surface as an ImportError / build failure long before this test - the
# guard is here so failure has a clear owner (G-5 split) and a
# maintainer sees the intent immediately.
# ---------------------------------------------------------------------------


def test_build_app_composes_starlette_router() -> None:
    from fdai.core.rbac.resolver import GroupMapping, RoleResolver
    from fdai.delivery.operator_api.auth import UnsafeClaimsExtractor, build_authenticator
    from fdai.delivery.operator_api.main import build_app
    from fdai.delivery.operator_api.read_model import InMemoryConsoleReadModel

    # Real RoleResolver bound to placeholder group ids - `build_app` never
    # invokes the resolver during route registration, but constructing a
    # real instance keeps the type contract honest so a future refactor
    # that DOES exercise the resolver here surfaces the failure early.
    placeholder = "00000000-0000-0000-0000-000000000000"
    resolver = RoleResolver(
        group_mapping=GroupMapping(
            reader_group_id=placeholder,
            contributor_group_id=placeholder,
            approver_group_id=placeholder,
            owner_group_id=placeholder,
            break_glass_group_id=placeholder,
        )
    )
    authenticator = build_authenticator(verifier=UnsafeClaimsExtractor(), resolver=resolver)
    app = build_app(authenticator=authenticator, read_model=InMemoryConsoleReadModel())
    snapshot = tuple(
        sorted(
            (
                tuple(sorted(getattr(route, "methods", ()) or ())),
                getattr(route, "path", ""),
                getattr(route, "name", ""),
            )
            for route in app.router.routes
        )
    )

    assert snapshot == _DEFAULT_ROUTE_SNAPSHOT


def test_default_http_envelopes_are_stable() -> None:
    from fdai.core.rbac.resolver import GroupMapping, RoleResolver
    from fdai.delivery.operator_api.auth import build_authenticator
    from fdai.delivery.operator_api.main import build_app
    from fdai.delivery.operator_api.read_model import InMemoryConsoleReadModel

    resolver = RoleResolver(
        group_mapping=GroupMapping(
            reader_group_id="reader-group",
            contributor_group_id="contributor-group",
            approver_group_id="approver-group",
            owner_group_id="owner-group",
            break_glass_group_id="break-glass-group",
        )
    )

    def verify(token: str) -> dict[str, object]:
        roles = [] if token == "no-role" else ["Reader"]
        return {"oid": "baseline-user", "roles": roles}

    app = build_app(
        authenticator=build_authenticator(verifier=verify, resolver=resolver),
        read_model=InMemoryConsoleReadModel(),
    )
    client = TestClient(app)

    missing_auth = client.get("/audit")
    malformed_auth = client.get(
        "/audit",
        headers={"Authorization": "Basic baseline-credential"},
    )
    forbidden = client.get("/audit", headers={"Authorization": "Bearer no-role"})
    invalid_query = client.get(
        "/audit?limit=invalid",
        headers={"Authorization": "Bearer reader"},
    )
    success = client.get("/audit", headers={"Authorization": "Bearer reader"})

    assert (missing_auth.status_code, missing_auth.json()) == (
        401,
        {"error": {"status": 401, "message": "Authorization header missing"}},
    )
    assert (malformed_auth.status_code, malformed_auth.json()) == (
        401,
        {
            "error": {
                "status": 401,
                "message": "Authorization header MUST use the Bearer scheme",
            }
        },
    )
    assert (forbidden.status_code, forbidden.json()) == (
        403,
        {
            "error": {
                "status": 403,
                "message": (
                    "principal lacks required role: any of "
                    "{Approver, Contributor, Owner, Reader} (has {})"
                ),
            }
        },
    )
    assert (invalid_query.status_code, invalid_query.json()) == (
        400,
        {
            "error": {
                "status": 400,
                "message": "query param 'limit' must be an integer, got 'invalid'",
            }
        },
    )
    assert (success.status_code, success.json()) == (
        200,
        {"items": [], "next_cursor": None},
    )
    for response in (missing_auth, malformed_auth, forbidden, invalid_query, success):
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["content-type"] == "application/json"


# ---------------------------------------------------------------------------
# H3: dev/ MUST NOT be imported anywhere in production code paths.
# ---------------------------------------------------------------------------


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    return modules


def test_dev_subpackage_is_not_imported_from_production_code() -> None:
    offenders: list[tuple[str, str]] = []
    for path in _REPO_ROOT.glob("src/**/*.py"):
        rel = path.relative_to(_REPO_ROOT)
        if "delivery/operator_api/dev" in str(rel).replace("\\", "/"):
            continue
        for module in _imported_modules(path):
            if module == "fdai.delivery.operator_api.dev" or module.startswith(
                "fdai.delivery.operator_api.dev."
            ):
                offenders.append((str(rel), module))
    assert not offenders, (
        "Production code imports fdai.delivery.operator_api.dev - a container "
        "build that drops dev/ would fail at runtime. Offenders:\n  "
        + "\n  ".join(f"{p}: {line}" for p, line in offenders)
    )


# ---------------------------------------------------------------------------
# H8: no external code reaches into a specific route module. Routes are
# implementation detail; callers use the ASGI app or the read_model
# facade instead.
# ---------------------------------------------------------------------------


def test_no_external_caller_reaches_into_routes() -> None:
    offenders: list[tuple[str, str]] = []
    for root in ("src", "scripts", "tools"):
        for path in (_REPO_ROOT / root).rglob("*.py"):
            rel_str = path.relative_to(_REPO_ROOT).as_posix()
            if rel_str.startswith("src/fdai/delivery/operator_api/"):
                continue
            for module in _imported_modules(path):
                if module.startswith("fdai.delivery.operator_api.routes."):
                    offenders.append((rel_str, module))
    assert not offenders, (
        "External src/ code imports specific route modules directly - "
        "routes are implementation detail; use the ASGI app or "
        "read_model. Offenders:\n  " + "\n  ".join(f"{p}: {line}" for p, line in offenders)
    )


def test_external_streaming_imports_match_declared_transitional_debt() -> None:
    inventory = json.loads(_MODULE_INVENTORY_PATH.read_text(encoding="utf-8"))
    rules = [
        entry
        for entry in inventory["import_surfaces"]
        if entry["module"].startswith("fdai.delivery.operator_api.streaming.")
        and "consumer_scope" in entry
    ]
    actual: list[tuple[str, str]] = []
    for path in (_REPO_ROOT / "src").rglob("*.py"):
        rel_str = path.relative_to(_REPO_ROOT).as_posix()
        if rel_str.startswith("src/fdai/delivery/operator_api/"):
            continue
        actual.extend(
            (rel_str, module)
            for module in _imported_modules(path)
            if module.startswith("fdai.delivery.operator_api.streaming.")
        )

    matches = {
        dependency: [
            rule
            for rule in rules
            if dependency[1] == rule["module"]
            and fnmatch.fnmatchcase(dependency[0], rule["consumer_scope"])
        ]
        for dependency in actual
    }
    assert all(len(declarations) == 1 for declarations in matches.values()), (
        f"External streaming imports must have one scoped transitional declaration: {matches}"
    )
    assert all(
        any(
            module == rule["module"] and fnmatch.fnmatchcase(path, rule["consumer_scope"])
            for path, module in actual
        )
        for rule in rules
    ), "Stale scoped streaming debt declaration"


# ---------------------------------------------------------------------------
# H9: main.py stays a declarative public facade. Composition and handlers
# live behind the imported modules; the facade defines no executable code.
# ---------------------------------------------------------------------------


def test_main_stays_declarative_public_facade() -> None:
    main_path = _OPERATOR_API_DIR / "main.py"
    tree = ast.parse(main_path.read_text(encoding="utf-8"))
    definitions = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert not definitions

    assert not any(isinstance(node, ast.Import) for node in tree.body)
    imports = [
        (node.module, tuple(alias.name for alias in node.names))
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
    ]
    assert imports == [
        (
            "fdai.delivery.operator_api.app.composition",
            (
                "ConversationRouteBindings",
                "GovernedRouteBindings",
                "HttpSurfaceBindings",
                "LifecycleBindings",
                "OperatorApiComposition",
                "OperatorApiRuntimeBindings",
                "OperatorApiValues",
                "ProjectionRouteBindings",
                "ReadViewBindings",
                "StreamRouteBindings",
            ),
        ),
        ("fdai.delivery.operator_api.app.config", ("OperatorApiConfig",)),
        ("fdai.delivery.operator_api.app.factory", ("build_app",)),
        (
            "fdai.delivery.operator_api.routes.busy_input_runtime",
            (
                "BusyInputRuntime",
                "BusyInputRuntimeMetrics",
                "build_postgres_busy_input_runtime",
            ),
        ),
    ]

    public_names = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
    )
    assert isinstance(public_names, ast.List)
    exported_names = [
        element.value for element in public_names.elts if isinstance(element, ast.Constant)
    ]
    assert exported_names == [
        "BusyInputRuntime",
        "BusyInputRuntimeMetrics",
        "ConversationRouteBindings",
        "GovernedRouteBindings",
        "HttpSurfaceBindings",
        "LifecycleBindings",
        "OperatorApiComposition",
        "OperatorApiConfig",
        "OperatorApiRuntimeBindings",
        "OperatorApiValues",
        "ProjectionRouteBindings",
        "ReadViewBindings",
        "StreamRouteBindings",
        "build_app",
        "build_postgres_busy_input_runtime",
    ]


# ---------------------------------------------------------------------------
# H10: streaming/ modules stay long-lived. A route handler would fit in
# routes/; streaming carries the SSE state machine. A file appearing in
# both surfaces is a smell.
# ---------------------------------------------------------------------------


def test_no_file_appears_in_both_routes_and_streaming() -> None:
    route_names = {p.stem for p in (_OPERATOR_API_DIR / "routes").glob("*.py")}
    stream_names = {p.stem for p in (_OPERATOR_API_DIR / "streaming").glob("*.py")}
    collisions = route_names & stream_names
    # __init__ is expected in both.
    collisions.discard("__init__")
    assert not collisions, (
        f"Files with identical names in routes/ and streaming/: "
        f"{sorted(collisions)}. Pick one home; if you need both a route "
        "and a stream for the same feature, name the stream module "
        "'<feature>_stream.py'."
    )
