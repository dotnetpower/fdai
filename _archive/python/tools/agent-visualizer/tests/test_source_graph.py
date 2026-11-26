"""Focused tests of the no-import, conservative Python graph extractor."""

# Pytest assertions are test expectations, not runtime security checks.
# ruff: noqa: S101

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from source_index import SourceIndex  # noqa: E402

AGENT_COMPOSITION = {
    "fdai.agents._framework.base": (
        "class Agent:\n def on_typed_message(self): pass\n def record(self): pass\n"
    ),
    "fdai.agents._framework.ingress": (
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        " from fdai.agents._framework.base import Agent as _AgentMixinBase\n"
        "else:\n"
        " _AgentMixinBase = object\n"
        "class IngressMixin(_AgentMixinBase):\n"
        " if TYPE_CHECKING:\n"
        "  def record(self): ...\n"
        " def ingest(self): self.record()\n"
        " def on_typed_message(self): pass\n"
    ),
    "fdai.agents.huginn": (
        "from fdai.agents._framework.base import Agent\n"
        "from fdai.agents._framework.ingress import IngressMixin\n"
        "class Huginn(IngressMixin, Agent):\n"
        " def introspect(self): pass\n"
    ),
}
HUGINN = "fdai.agents.huginn.Huginn"
INGRESS = "fdai.agents._framework.ingress.IngressMixin"
AGENT = "fdai.agents._framework.base.Agent"


def index_for(tmp_path: Path, modules: dict[str, str]) -> SourceIndex:
    paths = []
    for module, content in modules.items():
        path = tmp_path / "services/example/src" / f"{module.replace('.', '/')}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        paths.append(path)
    return SourceIndex(tmp_path, paths)


def test_import_alias_self_and_declared_receivers(tmp_path: Path) -> None:
    index = index_for(
        tmp_path,
        {
            "sample.helper": "def calculate(): pass\nclass Store:\n def read(self): pass\n",
            "sample.agent": (
                "from sample.helper import calculate as work, Store\n"
                "class Agent:\n"
                " def __init__(self, store: Store | None = None):\n  self.store = store\n"
                " def handle(self):\n  work()\n  self.other()\n  self.store.read()\n"
                " def other(self): pass\n"
            ),
        },
    )
    edges, _ = index.calls()
    assert {edge["target"] for edge in edges} == {
        "sample.helper.calculate",
        "sample.agent.Agent.other",
        "sample.helper.Store.read",
    }
    receiver = next(edge for edge in edges if edge["target"].endswith("Store.read"))
    assert receiver["resolution"] == "declared-receiver"


def test_unknown_dynamic_receivers_and_shadowed_names_are_not_guessed(tmp_path: Path) -> None:
    index = index_for(
        tmp_path,
        {
            "sample": (
                "def work(): pass\n"
                "def caller(work, provider):\n work()\n provider.read()\n"
                "def dynamic(provider):\n getattr(provider, 'secret-name')()\n"
            )
        },
    )
    edges, unresolved = index.calls()
    assert not edges
    assert {"work", "provider.read"} == {call["symbol"] for call in unresolved["sample.caller"]}
    assert "secret-name" not in str(unresolved)


def test_nested_function_bodies_are_not_calls_from_the_parent(tmp_path: Path) -> None:
    index = index_for(
        tmp_path,
        {"sample": ("def leaf(): pass\ndef outer():\n def inner():\n  leaf()\n inner()\n")},
    )
    edges, _ = index.calls()
    assert {(edge["source"], edge["target"]) for edge in edges} == {
        ("sample.outer", "sample.outer.inner"),
        ("sample.outer.inner", "sample.leaf"),
    }


def test_ambiguous_inherited_implementations_remain_unresolved(tmp_path: Path) -> None:
    index = index_for(
        tmp_path,
        {
            "sample": (
                "class One:\n def run(self): pass\n"
                "class Two:\n def run(self): pass\n"
                "class Three(One, Two):\n def caller(self): self.run()\n"
            )
        },
    )
    edges, unresolved = index.calls()
    assert not edges
    assert unresolved["sample.Three.caller"][0]["symbol"] == "self.run"


def test_relative_reexport_and_import_cycle_are_bounded(tmp_path: Path) -> None:
    index = index_for(
        tmp_path,
        {
            "sample.__init__": "from .helper import work\n",
            "sample.helper": "def work(): pass\n",
            "sample.client": "from sample import work\ndef run(): work()\n",
            "cycle.a": "from cycle.b import a\n",
            "cycle.b": "from cycle.a import b\n",
        },
    )
    edges, _ = index.calls()
    assert edges[0]["target"] == "sample.helper.work"
    assert isinstance(index.exported("cycle.a.a.b.a.b"), str)


def test_modules_are_never_executed(tmp_path: Path) -> None:
    index = index_for(
        tmp_path, {"sample": ("raise RuntimeError('MUST NOT EXECUTE')\ndef visible(): pass\n")}
    )
    assert "sample.visible" in index.functions


def test_nested_query_closure_preserves_self_without_guessing_shadowed_receivers(
    tmp_path: Path,
) -> None:
    index = index_for(
        tmp_path,
        {
            "sample": (
                "class Query:\n"
                " def fetch(self): pass\n"
                " def build(self):\n"
                "  def callback(): self.fetch()\n"
                "  def shadow(self): self.fetch()\n"
                "  return callback\n"
            )
        },
    )
    edges, unresolved = index.calls()
    assert {(edge["source"], edge["target"]) for edge in edges} == {
        ("sample.Query.build.callback", "sample.Query.fetch"),
    }
    assert unresolved["sample.Query.build.shadow"][0]["symbol"] == "self.fetch"


def test_agent_methods_follow_runtime_mro_through_mixins(tmp_path: Path) -> None:
    index = index_for(tmp_path, AGENT_COMPOSITION)

    # The TYPE_CHECKING-only base alias is `object` at runtime, so it adds no MRO entry.
    assert index.mro(HUGINN) == [HUGINN, INGRESS, AGENT]
    assert index.resolved_method(HUGINN, "on_typed_message") == f"{INGRESS}.on_typed_message"
    assert index.resolved_method(HUGINN, "ingest") == f"{INGRESS}.ingest"
    # A type-only stub is not a runtime member, so the framework implementation wins.
    assert f"{INGRESS}.record" not in index.functions
    assert index.resolved_method(HUGINN, "record") == f"{AGENT}.record"
    # Call resolution stays conservative: two inherited candidates remain unresolved.
    assert index.class_method(HUGINN, "on_typed_message") is None


def test_unindexed_bases_and_inconsistent_hierarchies_stay_unknown(tmp_path: Path) -> None:
    index = index_for(
        tmp_path,
        {
            "sample": (
                "from vendor.sdk import External\n"
                "class Local:\n def run(self): pass\n"
                "class Opaque(External, Local): pass\n"
                "class Known(Local, External): pass\n"
                "class A: pass\n"
                "class B(A): pass\n"
                "class C(A, B): pass\n"
            )
        },
    )

    assert index.resolved_method("sample.Opaque", "run") is None
    assert index.resolved_method("sample.Known", "run") == "sample.Local.run"
    assert index.mro("sample.C") is None


def test_agent_composition_excludes_the_shared_framework_base(tmp_path: Path) -> None:
    from export_graph import composed_members

    index = index_for(tmp_path, AGENT_COMPOSITION)

    assert composed_members(index, HUGINN) == [
        f"{INGRESS}.ingest",
        f"{INGRESS}.on_typed_message",
        f"{HUGINN}.introspect",
    ]
    without_base = index_for(
        tmp_path / "without-base",
        {"fdai.agents.huginn": "class Huginn:\n def introspect(self): pass\n"},
    )
    with pytest.raises(ValueError, match="framework base class is missing"):
        composed_members(without_base, HUGINN)
