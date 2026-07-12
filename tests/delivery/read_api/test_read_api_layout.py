"""Structural drift guards for the G-5 read_api split.

The delivery read_api (9,696 LOC) was grouped into routes/, streaming/,
and dev/ subpackages. These tests pin the shape so a stray file at the
top level, a broken URL registration, or a caller reaching into dev/
from production code surfaces as a test failure.

Tracker: #14, issue #19.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_READ_API_DIR = _REPO_ROOT / "src" / "fdai" / "delivery" / "read_api"

# Files that legitimately live at the top level (not under a subpackage).
# Foundational read-API contracts + concrete composition-root entrypoints
# only. Route handlers, SSE emitters, and dev harnesses stay in their
# subpackages; the concrete `PostgresConsoleReadModel` is the natural
# sibling of `read_model.py` (the Protocol it implements) and `prod.py`
# is the production counterpart to `dev/local.py`.
_TOP_LEVEL_ALLOWED = frozenset(
    {
        "__init__.py",
        "main.py",
        "auth.py",
        "entra_verifier.py",
        "read_model.py",
        "postgres_read_model.py",
        "prod.py",
    }
)


# ---------------------------------------------------------------------------
# H1: layout drift - top-level *.py MUST be exactly the allowed set.
# ---------------------------------------------------------------------------


def test_top_level_read_api_is_only_allowed_files() -> None:
    top_pyfiles = {p.name for p in _READ_API_DIR.glob("*.py")}
    extras = top_pyfiles - _TOP_LEVEL_ALLOWED
    assert not extras, (
        f"Top-level read_api/*.py must be limited to "
        f"{sorted(_TOP_LEVEL_ALLOWED)}. Move {sorted(extras)} into "
        "routes/, streaming/, or dev/. See G-5 in tracker #14."
    )


def test_three_subpackages_exist() -> None:
    for name in ("routes", "streaming", "dev"):
        sub = _READ_API_DIR / name
        assert sub.is_dir(), f"read_api/{name}/ sub-package missing"
        assert (sub / "__init__.py").is_file(), f"read_api/{name}/__init__.py missing"


# ---------------------------------------------------------------------------
# H2: URL/route shape stability. build_app() succeeds and produces a
# non-empty starlette Router. A regression that broke composition would
# surface as an ImportError / build failure long before this test - the
# guard is here so failure has a clear owner (G-5 split) and a
# maintainer sees the intent immediately.
# ---------------------------------------------------------------------------


def test_build_app_composes_starlette_router() -> None:
    from fdai.core.rbac.resolver import GroupMapping, RoleResolver
    from fdai.delivery.read_api.auth import UnsafeClaimsExtractor, build_authenticator
    from fdai.delivery.read_api.main import build_app
    from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel

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
    routes = list(app.router.routes)
    # Baseline: 4 core routes (audit, kpi, hil-queue, healthz) always
    # register. Extra routes come from opt-in seams (config flags,
    # additional readers) so 4 is the floor.
    assert len(routes) >= 4, (
        f"build_app() router has only {len(routes)} routes - a G-5 move "
        "may have dropped a router-list entry."
    )
    # Sanity: the four names are the ones the split preserved.
    route_names = {getattr(r, "name", "") for r in routes}
    for expected in ("get_audit", "get_kpi", "get_hil_queue", "healthz"):
        assert expected in route_names, (
            f"core route {expected!r} missing after the split; got names {sorted(route_names)}"
        )


# ---------------------------------------------------------------------------
# H3: dev/ MUST NOT be imported anywhere in production code paths.
# ---------------------------------------------------------------------------


_DEV_IMPORT = re.compile(r"(?:from|import)\s+fdai\.delivery\.read_api\.dev(?:\.|$|\s)")


def test_dev_subpackage_is_not_imported_from_production_code() -> None:
    offenders: list[tuple[str, str]] = []
    for path in _REPO_ROOT.glob("src/**/*.py"):
        rel = path.relative_to(_REPO_ROOT)
        # dev/local.py may legitimately reference itself; skip.
        if "delivery/read_api/dev" in str(rel).replace("\\", "/"):
            continue
        body = path.read_text(encoding="utf-8")
        for line in body.splitlines():
            if _DEV_IMPORT.search(line):
                offenders.append((str(rel), line.strip()))
    assert not offenders, (
        "Production code imports fdai.delivery.read_api.dev - a container "
        "build that drops dev/ would fail at runtime. Offenders:\n  "
        + "\n  ".join(f"{p}: {line}" for p, line in offenders)
    )


# ---------------------------------------------------------------------------
# H4: routes/ and streaming/ each have at least the expected file count.
# Catches a mis-move that leaves a file at the top level or in the wrong
# subdir.
# ---------------------------------------------------------------------------


def test_routes_and_streaming_are_populated() -> None:
    routes = list((_READ_API_DIR / "routes").glob("*.py"))
    # 18 moved route modules + __init__.py.
    assert len(routes) >= 18, (
        f"routes/ only has {len(routes)} .py files (expected >= 18). "
        "A file may have been left at the top level."
    )
    streams = list((_READ_API_DIR / "streaming").glob("*.py"))
    # 3 SSE modules + __init__.py.
    assert len(streams) >= 4, f"streaming/ only has {len(streams)} .py files (expected >= 4)."


# ---------------------------------------------------------------------------
# H8: no external code reaches into a specific route module. Routes are
# implementation detail; callers use the ASGI app or the read_model
# facade instead.
# ---------------------------------------------------------------------------


_ROUTE_IMPORT = re.compile(
    r"(?:from|import)\s+fdai\.delivery\.read_api\.routes\.[a-zA-Z_][a-zA-Z0-9_]*"
)


def test_no_external_caller_reaches_into_routes() -> None:
    # External = outside src/fdai/delivery/read_api/ and outside tests/.
    # Tests may introspect the split.
    offenders: list[tuple[str, str]] = []
    for path in _REPO_ROOT.glob("src/**/*.py"):
        rel_str = str(path.relative_to(_REPO_ROOT)).replace("\\", "/")
        if rel_str.startswith("src/fdai/delivery/read_api/"):
            continue
        body = path.read_text(encoding="utf-8")
        for line in body.splitlines():
            if _ROUTE_IMPORT.search(line):
                offenders.append((rel_str, line.strip()))
    assert not offenders, (
        "External src/ code imports specific route modules directly - "
        "routes are implementation detail; use the ASGI app or "
        "read_model. Offenders:\n  " + "\n  ".join(f"{p}: {line}" for p, line in offenders)
    )


# ---------------------------------------------------------------------------
# H9: main.py stays a slim composition root. It orchestrates route
# families; it MUST NOT define handlers or business logic itself. A
# proxy metric: the file's LOC MUST NOT grow past ~1200 after the split.
# (The original was 1031 LOC and the split does not touch its shape;
# add margin for docstrings.)
# ---------------------------------------------------------------------------


def test_main_stays_slim_composition_root() -> None:
    main_path = _READ_API_DIR / "main.py"
    loc = main_path.read_text().count("\n")
    assert loc < 1200, (
        f"read_api/main.py has grown to {loc} LOC (> 1200). Extract "
        "the added handler logic into a routes/ module instead."
    )


# ---------------------------------------------------------------------------
# H10: streaming/ modules stay long-lived. A route handler would fit in
# routes/; streaming carries the SSE state machine. A file appearing in
# both surfaces is a smell.
# ---------------------------------------------------------------------------


def test_no_file_appears_in_both_routes_and_streaming() -> None:
    route_names = {p.stem for p in (_READ_API_DIR / "routes").glob("*.py")}
    stream_names = {p.stem for p in (_READ_API_DIR / "streaming").glob("*.py")}
    collisions = route_names & stream_names
    # __init__ is expected in both.
    collisions.discard("__init__")
    assert not collisions, (
        f"Files with identical names in routes/ and streaming/: "
        f"{sorted(collisions)}. Pick one home; if you need both a route "
        "and a stream for the same feature, name the stream module "
        "'<feature>_stream.py'."
    )
