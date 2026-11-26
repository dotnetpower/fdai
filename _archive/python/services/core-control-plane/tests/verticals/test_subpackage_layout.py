"""Structural drift guards for the G-6 verticals sub-package split.

The three verticals (resilience, change_safety, cost_governance) live
as sub-packages under ``fdai.core.verticals``. These tests pin the
shape so a stray addition (new top-level file in verticals/), a broken
Protocol conformance, or a cross-vertical import surfaces here instead
of at runtime.

Tracker: #14, issue #20.
"""

from __future__ import annotations

import re
from pathlib import Path

import fdai.core.verticals as verticals_pkg
import pytest
from fdai.core.verticals import Vertical
from fdai.core.verticals.registry import VerticalDescriptor
from fdai.shared.contracts.models import Category

_REPO_ROOT = Path(__file__).resolve().parents[4]
_VERTICALS_DIR = (
    _REPO_ROOT / "services" / "core-control-plane" / "src" / "fdai" / "core" / "verticals"
)

_VERTICAL_NAMES = frozenset({"resilience", "change_safety", "cost_governance"})

_CATEGORY_BY_VERTICAL = {
    "resilience": Category.RELIABILITY,
    "change_safety": Category.CONFIG_DRIFT,
    "cost_governance": Category.COST,
}


# ---------------------------------------------------------------------------
# H1: top-level layout - each vertical is a directory; the only .py files at
# the top level are the shared plumbing (registry, base, __init__).
# ---------------------------------------------------------------------------


def test_top_level_verticals_is_only_shared_plumbing() -> None:
    top_pyfiles = {p.name for p in _VERTICALS_DIR.glob("*.py")}
    allowed = {"__init__.py", "base.py", "registry.py"}
    extras = top_pyfiles - allowed
    assert not extras, (
        f"Top-level verticals/*.py must be limited to {sorted(allowed)}. "
        f"Move {sorted(extras)} into a per-vertical sub-package under "
        "verticals/<vertical>/. See G-6 in tracker #14."
    )


def test_every_vertical_subpackage_exists() -> None:
    for name in _VERTICAL_NAMES:
        sub = _VERTICALS_DIR / name
        assert sub.is_dir(), f"verticals/{name}/ sub-package missing"
        assert (sub / "__init__.py").is_file(), f"verticals/{name}/__init__.py facade missing"


# ---------------------------------------------------------------------------
# H2 + H6: Vertical Protocol - the shared contract. Every registered
# VerticalDescriptor MUST conform (name kebab-case slug, description
# non-empty string, structural check via runtime_checkable Protocol).
# ---------------------------------------------------------------------------


def _list_vertical_descriptors() -> list[VerticalDescriptor]:
    """Instantiate a canonical descriptor per subpackage for conformance testing."""
    return [
        VerticalDescriptor(
            vertical_id=name.replace("_", "-"),
            display_name=name.replace("_", " ").title(),
            category=_CATEGORY_BY_VERTICAL[name],
            rule_source_ids=("custom",),
            enabled=False,
        )
        for name in sorted(_VERTICAL_NAMES)
    ]


@pytest.mark.parametrize("descriptor", _list_vertical_descriptors())
def test_descriptor_conforms_to_vertical_protocol(
    descriptor: VerticalDescriptor,
) -> None:
    assert isinstance(descriptor, Vertical), (
        f"{descriptor.vertical_id!r} descriptor does not satisfy Vertical Protocol"
    )


@pytest.mark.parametrize("descriptor", _list_vertical_descriptors())
def test_vertical_name_is_kebab_case_slug(descriptor: VerticalDescriptor) -> None:
    # ActionType / rule catalog IDs are kebab-case; verticals share the
    # vocabulary so cross-references stay grep-friendly.
    assert re.fullmatch(r"[a-z][a-z0-9-]{0,63}", descriptor.vertical_id), (
        f"vertical_id {descriptor.vertical_id!r} must be kebab-case slug"
    )
    assert descriptor.display_name, "display_name MUST be a non-empty string"


# ---------------------------------------------------------------------------
# H3: facade re-export completeness. Every submodule public symbol
# (class or callable exposed via that submodule's __all__) MUST be
# re-exported at the vertical's __init__ facade.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("vertical", sorted(_VERTICAL_NAMES))
def test_vertical_facade_reexports_every_public_symbol(vertical: str) -> None:
    import importlib

    facade = importlib.import_module(f"fdai.core.verticals.{vertical}")
    facade_all = set(getattr(facade, "__all__", ()))

    # Discover public symbols across every submodule under this vertical.
    for path in (_VERTICALS_DIR / vertical).glob("*.py"):
        if path.name == "__init__.py":
            continue
        # CLI entry-point modules ('*_cli.py') export only a `main`
        # runner - not primary re-export surface for library callers.
        if path.stem.endswith("_cli"):
            continue
        sub = importlib.import_module(f"fdai.core.verticals.{vertical}.{path.stem}")
        sub_all = getattr(sub, "__all__", None)
        if sub_all is None:
            # Modules without an explicit __all__ (e.g. CLI harnesses) are
            # exempt - they are not primary re-export surface.
            continue
        gap = [name for name in sub_all if name not in facade_all]
        assert not gap, (
            f"verticals/{vertical}/__init__.py does not re-export "
            f"{gap} from submodule .{path.stem}. Either add to the facade "
            f"or drop from the submodule's __all__."
        )


# ---------------------------------------------------------------------------
# H4: cross-vertical import boundary. change_safety/ MUST NOT import from
# resilience/ or cost_governance/, etc. Cross-vertical composition is the
# job of the composition root, not one vertical reaching into another.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("vertical", sorted(_VERTICAL_NAMES))
def test_no_cross_vertical_imports(vertical: str) -> None:
    peers = _VERTICAL_NAMES - {vertical}
    peer_re = re.compile(
        rf"^\s*(?:from|import)\s+fdai\.core\.verticals\.({'|'.join(peers)})",
        re.M,
    )
    offenders: list[tuple[str, str]] = []
    for path in (_VERTICALS_DIR / vertical).rglob("*.py"):
        body = path.read_text(encoding="utf-8")
        for match in peer_re.finditer(body):
            offenders.append((str(path.relative_to(_REPO_ROOT)), match.group(0).strip()))
    assert not offenders, (
        f"vertical {vertical!r} reaches into a peer vertical directly: "
        f"{offenders}. Compose them at the composition root instead."
    )


# ---------------------------------------------------------------------------
# H5: registry integration. Three descriptors register cleanly and
# roundtrip through the registry lookup.
# ---------------------------------------------------------------------------


def test_registry_accepts_three_vertical_descriptors() -> None:
    from fdai.core.verticals import VerticalRegistry

    registry = VerticalRegistry()
    for descriptor in _list_vertical_descriptors():
        registry.register(descriptor)
    ids = {d.vertical_id for d in registry.all()}
    assert ids == {"resilience", "change-safety", "cost-governance"}


# ---------------------------------------------------------------------------
# H7: cost_governance scaffold is populated. An empty scaffold silently
# ships as unused; assert at least one class exists in the subpackage.
# ---------------------------------------------------------------------------


def test_cost_governance_scaffold_is_not_empty() -> None:
    from fdai.core.verticals import cost_governance

    exported = getattr(cost_governance, "__all__", ())
    assert exported, (
        "verticals/cost_governance/__init__.py __all__ is empty; the "
        "scaffold ships unused. Move at least one FinOps primitive here."
    )


# ---------------------------------------------------------------------------
# H10: facade docstring anchors - the design intent stays legible so a
# well-meaning refactor cannot silently rewrite the sub-package purpose.
# ---------------------------------------------------------------------------


def test_top_facade_docstring_pins_vertical_names() -> None:
    doc = (verticals_pkg.__doc__ or "").lower()
    for name in ("resilience", "change safety", "cost governance"):
        assert name in doc, (
            f"verticals/__init__.py docstring lost the anchor '{name}' - "
            "the vertical taxonomy is drifting."
        )
