"""Prompt applies_to <-> llm-registry capability consistency gate.

A base/pack prompt's ``applies_to`` names the capabilities the composer
looks it up by. If a capability is a typo (or a registry entry is later
renamed/removed), the prompt silently stops matching and composition
fails at bind time - not at test time. Nothing cross-checked the two
sides, so this gate does: every ``applies_to`` capability MUST be either
a real ``llm-registry.yaml`` capability OR an explicitly allowlisted
prompt-only capability.

The only prompt-only capability today is the console narrator, which
reuses a T1 deployment and has no registry entry of its own (see
``rule-catalog/prompts/README.md``). Discovered while adding the rubric
judge: the narrator prompt already referenced a capability absent from
the registry, undetected because no gate existed.
"""

from __future__ import annotations

from pathlib import Path

from fdai.core.prompts.registry import FileSystemPromptRegistry
from fdai.core.prompts.types import PromptLayer
from fdai.rule_catalog.schema.llm_registry import load_llm_registry_from_yaml

_REPO = Path(__file__).resolve().parents[2]
_CATALOG = _REPO / "rule-catalog"

# Capabilities that intentionally have NO llm-registry entry. The console
# narrator reuses t1.judge, t2.proposer selects the reasoner pair, and the
# Norns review prompt selects t2.reasoner.primary/secondary off-path. Adding
# to this set requires a stated reason (a new prompt-only lookup key).
_PROMPT_ONLY_CAPABILITIES = frozenset({"console.narrator", "norns.post-turn-review", "t2.proposer"})


def _registry_capabilities() -> set[str]:
    reg = load_llm_registry_from_yaml(_CATALOG / "llm-registry.yaml")
    return set(reg.models)


def test_every_prompt_applies_to_is_a_known_capability() -> None:
    known = _registry_capabilities() | _PROMPT_ONLY_CAPABILITIES
    prompts = FileSystemPromptRegistry(_CATALOG)
    offenders = [
        f"{art.id} (layer={art.layer.value}) -> {cap!r}"
        for art in prompts.artifacts()
        for cap in art.applies_to
        if cap not in known
    ]
    assert not offenders, (
        "prompt applies_to references capabilities not in llm-registry.yaml "
        f"(nor allowlisted prompt-only): {offenders}"
    )


def test_rubric_prompt_is_shipped_with_rubric_layer() -> None:
    # The rubric judge prompt ships under the ``rubric`` layer - the same
    # role-layer pattern as t2-critic / t2-judge. NOTE: role layers
    # (critic/judge/rubric) are NOT assembled by the composer's BASE/PACK
    # path (``get_base`` filters PromptLayer.BASE only); a fork wiring the
    # judge loads the artifact by id/layer itself. This test pins the
    # shipped shape so a fork can rely on it.
    prompts = FileSystemPromptRegistry(_CATALOG)
    rubric_arts = [a for a in prompts.artifacts() if a.id == "t2-rubric"]
    assert len(rubric_arts) == 1
    art = rubric_arts[0]
    assert art.layer is PromptLayer.RUBRIC
    assert "t2.rubric.judge" in art.applies_to


def test_prompt_only_capabilities_are_locked_to_the_allowlist() -> None:
    # Guard: if a NEW capability appears in a prompt's applies_to that is
    # NOT in the registry, this fails so the allowlist is widened
    # deliberately (with a reason), never silently.
    registry = _registry_capabilities()
    prompts = FileSystemPromptRegistry(_CATALOG)
    used_prompt_only = {
        cap for art in prompts.artifacts() for cap in art.applies_to if cap not in registry
    }
    assert used_prompt_only <= _PROMPT_ONLY_CAPABILITIES, (
        f"unexpected prompt-only capabilities: {used_prompt_only - _PROMPT_ONLY_CAPABILITIES}"
    )
