"""Structural drift guards for the G-3 composition/ split.

The 1018-LOC composition.py became a package with a facade and three
extraction files. These tests pin the layout, the facade completeness,
the no-circular-import contract, and the LOC ceiling so the split
cannot silently re-monolith.

Tracker: #14, issue #17.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import fdai.composition as composition_pkg

_REPO_ROOT = Path(__file__).resolve().parents[1]
_COMP_DIR = _REPO_ROOT / "src" / "fdai" / "composition"

_EXPECTED_FILES = frozenset(
    {
        "__init__.py",
        "_helpers.py",
        "wire_llm.py",
        "wire_azure.py",
        "wire_change_feed.py",
        # Durable execution profile and ledger binding.
        "wire_execution_backends.py",
        # Azure observation adapters extracted from the main Azure wire.
        "wire_observation_providers.py",
        # Governed trajectory source, export, store, and administration wiring.
        "wire_trajectory.py",
        # Validates additive fork capability bundles and keeps their
        # catalog cross-reference assembly out of the facade.
        "wire_capabilities.py",
        # Application-level ORR wiring: composes assurance + preflight through
        # injected providers, audits the verdict, then publishes a read model.
        "readiness.py",
        # Extracted from wire_azure.py (G-4) to keep the file under the
        # per-file LOC ceiling; assembles the metric-provider composite
        # from whichever telemetry backends the deploy exposes.
        "wire_metric_provider.py",
        # Binds the evidence-only browser provider, exact origin policies,
        # immutable artifact store, and custody sink as one fail-closed seam.
        "wire_browser_evidence.py",
    }
)

_PUBLIC_NAMES = (
    "default_container",
    "default_container_from_env",
    "Container",
    "LlmBindings",
    "LlmBindingsUnavailableError",
    "AzureWireOverrides",
    "wire_azure_container",
    "bind_azure_llm_bindings",
    "bind_azure_monitor_logs",
    "bind_azure_inventory",
    "bind_embedding_knowledge_source",
    "bind_github_change_feed",
    "load_pricing_table",
    "install_capability_bundle",
    "OperationalReadinessService",
    "bind_browser_evidence",
)

# Names that MUST also appear in __all__ (subset of _PUBLIC_NAMES). The
# small bind_* helpers are callable but not (yet) in __all__; that's an
# older upstream decision the split preserves rather than expands.
_ALL_MEMBERS = (
    "default_container",
    "default_container_from_env",
    "Container",
    "LlmBindings",
    "LlmBindingsUnavailableError",
    "AzureWireOverrides",
    "wire_azure_container",
    "bind_azure_llm_bindings",
    "load_pricing_table",
    "install_capability_bundle",
    "OperationalReadinessService",
    "bind_browser_evidence",
)


# ---------------------------------------------------------------------------
# H1: package layout - exactly the four files exist.
# ---------------------------------------------------------------------------


def test_composition_package_layout() -> None:
    present = {p.name for p in _COMP_DIR.glob("*.py")}
    missing = _EXPECTED_FILES - present
    extra = present - _EXPECTED_FILES
    assert not missing, f"composition/ missing files: {sorted(missing)}"
    assert not extra, (
        f"composition/ has unexpected file(s): {sorted(extra)}. Add to "
        "the expected set (with justification) or move the code into "
        "one of the wire files."
    )


# ---------------------------------------------------------------------------
# H2: public-API completeness - every name the pre-split file exported
# still resolves at the package facade.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _PUBLIC_NAMES)
def test_public_name_still_resolves(name: str) -> None:
    assert hasattr(composition_pkg, name), (
        f"public name {name!r} was lost in the G-3 split. Add a "
        "re-export from the appropriate wire file to __init__.py."
    )


def test_public_names_in_all() -> None:
    exported = set(getattr(composition_pkg, "__all__", ()))
    for name in _ALL_MEMBERS:
        assert name in exported, (
            f"{name!r} is importable but missing from __all__. Wildcard "
            "imports (from fdai.composition import *) would drop it."
        )


# ---------------------------------------------------------------------------
# H3: no external caller reaches into a specific wire file. The wire
# files are internal composition detail; callers use the facade.
# ---------------------------------------------------------------------------


_WIRE_IMPORT = re.compile(r"(?:from|import)\s+fdai\.composition\.(?:wire_[a-z]+|_helpers)")


def test_no_external_caller_reaches_into_wire_files() -> None:
    offenders: list[tuple[str, str]] = []
    for path in _REPO_ROOT.glob("src/**/*.py"):
        rel_str = str(path.relative_to(_REPO_ROOT)).replace("\\", "/")
        if rel_str.startswith("src/fdai/composition/"):
            continue
        body = path.read_text(encoding="utf-8")
        for line in body.splitlines():
            if _WIRE_IMPORT.search(line):
                offenders.append((rel_str, line.strip()))
    assert not offenders, (
        "External src/ code imports composition wire files directly - "
        "they are internal. Import from 'fdai.composition' facade:\n  "
        + "\n  ".join(f"{p}: {line}" for p, line in offenders)
    )


# ---------------------------------------------------------------------------
# H4: per-file LOC ceiling. wire_llm holds the ~350-LOC Azure OpenAI
# binder and legitimately runs past 400; the other three MUST stay
# under 400.
# ---------------------------------------------------------------------------


_LOC_LIMITS = {
    "__init__.py": 400,
    "_helpers.py": 400,
    "wire_azure.py": 400,
    "wire_llm.py": 800,  # holds the ~308-LOC bind_azure_llm_bindings body
}


@pytest.mark.parametrize("filename,limit", sorted(_LOC_LIMITS.items()))
def test_file_stays_under_ceiling(filename: str, limit: int) -> None:
    path = _COMP_DIR / filename
    loc = path.read_text().count("\n")
    assert loc <= limit, (
        f"composition/{filename} has {loc} LOC (> {limit}). Split "
        "further along a natural axis (one binder per file, one adapter "
        "family per file, ...)."
    )


# ---------------------------------------------------------------------------
# H5: no circular imports at collection time. If __init__.py, _helpers,
# wire_llm, and wire_azure form a cycle, importing the package raises.
# The test just imports and checks the facade returned the expected
# names.
# ---------------------------------------------------------------------------


def test_no_circular_import() -> None:
    # Re-import to prove the module resolves cleanly from a cold state.
    import importlib

    module = importlib.reload(composition_pkg)
    for name in _PUBLIC_NAMES:
        assert hasattr(module, name), (
            f"reload lost {name!r} - a circular import likely masks it "
            "silently under the original import."
        )


# ---------------------------------------------------------------------------
# H6: wire files stay wire files - they MUST NOT re-import from each
# other except via _helpers. Cross-wire imports collapse the "one
# binder per file" boundary.
# ---------------------------------------------------------------------------


def test_wire_files_do_not_import_each_other() -> None:
    # wire_azure MAY import bind_azure_llm_bindings from wire_llm (it
    # composes it), attach_metric_provider from wire_metric_provider, and
    # attach_observation_providers from wire_observation_providers.
    # All other cross-wire imports are forbidden.
    allowed = {
        ("wire_azure.py", "wire_llm.py"),
        ("wire_azure.py", "wire_metric_provider.py"),
        ("wire_azure.py", "wire_observation_providers.py"),
    }
    offenders: list[tuple[str, str, str]] = []
    for path in _COMP_DIR.glob("wire_*.py"):
        body = path.read_text(encoding="utf-8")
        for match in re.finditer(r"(?:from|import)\s+\.(wire_[a-z_]+)", body):
            target = f"{match.group(1)}.py"
            pair = (path.name, target)
            if pair in allowed:
                continue
            offenders.append((path.name, target, match.group(0).strip()))
    assert not offenders, "wire files import each other outside the allowlist: " + str(offenders)


# ---------------------------------------------------------------------------
# H7: _helpers.py is private - underscore prefix means "not for external
# consumption". Reaching into _helpers from outside the composition
# package defeats the split.
# ---------------------------------------------------------------------------


def test_helpers_is_private() -> None:
    # No entry in __all__ or facade points at _helpers.
    exported = set(getattr(composition_pkg, "__all__", ()))
    assert "_helpers" not in exported


# ---------------------------------------------------------------------------
# H8: facade docstring pins the package intent.
# ---------------------------------------------------------------------------


def test_facade_docstring_mentions_g3() -> None:
    doc = (composition_pkg.__doc__ or "").lower()
    # The docstring MUST reference the tracker so a maintainer looking
    # at the __init__.py knows where the design lives.
    for anchor in ("composition", "seam", "container"):
        assert anchor in doc, f"composition/__init__.py docstring lost anchor {anchor!r}"


# ---------------------------------------------------------------------------
# H9: default_container is instantiable with a stock AppConfig so a
# smoke test would catch a broken binder.
# ---------------------------------------------------------------------------


def test_default_container_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    # Use the env-loader path with all-defaults so the pydantic AppConfig
    # required fields resolve. This is the actual bootstrap flow the CLI
    # uses; if it works there, it works here.
    from fdai.composition import default_container_from_env

    required_env = {
        "AZURE_TENANT_ID": "00000000-0000-0000-0000-000000000000",
        "AZURE_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000000",
        "AZURE_REGION": "krc",
        "KAFKA_BOOTSTRAP_SERVERS": "events.example.local:9093",
        "KAFKA_TOPIC_EVENTS": "fdai.events",
        "POSTGRES_HOST": "postgres.example.local",
        "POSTGRES_DATABASE": "fdai",
        "RUNTIME_ENV": "dev",
        "LLM_MODE": "local-fake",
    }
    for key, value in required_env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("LLM_RESOLVED_MODELS_PATH", raising=False)

    container = default_container_from_env()
    assert container.config is not None
    assert container.schema_registry is not None
