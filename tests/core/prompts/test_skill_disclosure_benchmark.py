"""Token benchmarks for progressive runtime skill disclosure."""

from __future__ import annotations

import math

import pytest
import yaml

from fdai.core.prompts import SkillDisclosureRequest, SkillSelectionStatus
from fdai.core.prompts.skill_disclosure import compose_skill_disclosure
from fdai.core.skills import RuntimeSkill, SkillCatalog, skill_body_digest


class _Verifier:
    def verify(self, skill: RuntimeSkill, raw_markdown: bytes) -> bool:
        return True


def _catalog() -> tuple[SkillCatalog, _Verifier, tuple[str, ...]]:
    verifier = _Verifier()
    catalog = SkillCatalog()
    names: list[str] = []
    topics = (
        "network incident",
        "database latency",
        "identity access",
        "storage capacity",
        "cost spike",
        "backup recovery",
        "kubernetes health",
        "service availability",
        "deployment failure",
        "certificate expiry",
        "queue saturation",
        "policy drift",
        "log investigation",
        "metric anomaly",
        "change review",
        "audit evidence",
    )
    for index, topic in enumerate(topics):
        name = f"operator-skill-{index:02d}"
        body = f"Procedure for {topic}.\n" + (f"Step {index} uses bounded evidence.\n" * 64)
        manifest = {
            "name": name,
            "version": "1.0.0",
            "description": f"Governed procedure for {topic}.",
            "source": "publisher.example",
            "body_sha256": skill_body_digest(body),
            "required_tools": ["query_inventory"],
            "allowed_agents": ["Bragi"],
        }
        raw = f"---\n{yaml.safe_dump(manifest, sort_keys=False)}---\n{body}".encode()
        catalog = catalog.install(raw, verifier=verifier).enable(
            name,
            available_tools=frozenset({"query_inventory"}),
            known_agents=frozenset({"Bragi"}),
        )
        names.append(name)
    return catalog, verifier, tuple(names)


@pytest.mark.parametrize(
    ("query", "selected_index"),
    [
        ("investigate network incident", 0),
        ("explain cost spike", 4),
        ("diagnose deployment failure", 8),
    ],
)
def test_progressive_disclosure_reduces_representative_prompt_tokens(
    query: str,
    selected_index: int,
) -> None:
    catalog, verifier, names = _catalog()
    tools = frozenset({"query_inventory"})
    full_projection = catalog.prompt_for(
        agent="Bragi",
        available_tools=tools,
        max_chars=128 * 1024,
    )
    progressive = compose_skill_disclosure(
        catalog=catalog,
        verifier=verifier,
        request=SkillDisclosureRequest(
            agent="Bragi",
            available_tools=tools,
            query=query,
            selected_skill_names=(names[selected_index],),
        ),
    )
    progressive_projection = "\n\n".join(layer.body for layer in progressive.layers)
    baseline_tokens = math.ceil(len(full_projection) / 4)
    progressive_tokens = math.ceil(len(progressive_projection) / 4)
    reduction = 1 - (progressive_tokens / baseline_tokens)

    assert baseline_tokens > progressive_tokens
    assert reduction >= 0.75
    assert len(progressive.records) == 1
    assert progressive.records[0].status is SkillSelectionStatus.SELECTED
    assert progressive.records[0].version == "1.0.0"
    assert progressive.records[0].body_sha256 is not None
