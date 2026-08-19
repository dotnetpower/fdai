"""Prompt applies_to <-> llm-registry capability consistency gate.

A base/pack prompt's ``applies_to`` names the capabilities the composer
looks it up by. If a capability is a typo (or a registry entry is later
renamed/removed), the prompt silently stops matching and composition
fails at bind time - not at test time. Nothing cross-checked the two
sides, so this gate does: every ``applies_to`` capability MUST be either
a real ``llm-registry.yaml`` capability OR an explicitly allowlisted
prompt-only capability.

Prompt-only capabilities reuse resolved deployment slots and have no registry
entry of their own (see ``rule-catalog/prompts/README.md``). Discovered while
adding the rubric judge: the narrator prompt already referenced a capability
absent from the registry, undetected because no gate existed.
"""

from __future__ import annotations

from pathlib import Path

from fdai.core.prompts.registry import FileSystemPromptRegistry
from fdai.core.prompts.types import PromptLayer
from fdai.rule_catalog.schema.llm_registry import load_llm_registry_from_yaml

_REPO = Path(__file__).resolve().parents[4]
_CATALOG = _REPO / "rule-catalog"

# Capabilities that intentionally have NO llm-registry entry. The console
# narrator reuses t1.judge, t2.proposer selects the reasoner pair, and the
# Norns review prompt selects t2.reasoner.primary/secondary off-path. Semantic
# frame/plan prompts use the same resolved reasoner candidates as two strict
# calls. Adding to this set requires a stated reason (a prompt-only lookup key).
_PROMPT_ONLY_CAPABILITIES = frozenset(
    {
        "console.narrator",
        "norns.post-turn-review",
        "semantic.query.frame",
        "semantic.query.plan",
        "t2.proposer",
    }
)


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


def test_semantic_plan_prompt_pins_the_object_set_verifier_envelope() -> None:
    prompts = FileSystemPromptRegistry(_CATALOG)
    artifacts = [
        artifact for artifact in prompts.artifacts() if artifact.id == "semantic-query-plan"
    ]

    assert len(artifacts) == 1
    body = artifacts[0].body
    assert 'arguments exactly shaped as {"definition":{"selector"' in body
    assert '"kind":"object_type" or "interface"' in body
    assert '"as_of":"the exact supplied evaluation_time"' in body
    assert '"purpose":"the supplied purpose"' in body
    assert '"limit":1..1000' in body
    assert '"function_name":"query.manifest"' in body
    assert '"kinds"' in body
    assert 'arguments exactly shaped as {"operation":"count","group_by":[],"limit":1..1000}' in body
    assert '"operator":"exists"' in body
    assert '"operator":"equals","equals"' in body
    assert '"operator":"in","values"' in body
    assert '"operator":"contains","equals"' in body
    assert "one direct key from the selected descriptor's properties map" in body
    assert "never a projected row path such as properties.type" in body
    assert "never a natural-language alias such as resource_type or ResourceType" in body
    assert "without an exact root id uses one topology_at node" in body
    assert "do not use object_set, project, or query.ontology_relationships" in body
    assert "uses exactly one object_set node with one or more definition.predicates" in body
    assert "unless the request explicitly combines distinct sets" in body
    assert "row exposes exactly id, object_type, and properties" in body
    assert "properties.<property_name>" in body


def test_semantic_prompts_pin_incident_evidence_without_cause_authority() -> None:
    prompts = FileSystemPromptRegistry(_CATALOG)
    frame = prompts.get_base("semantic.query.frame")
    plan = prompts.get_base("semantic.query.plan")

    assert frame.version == 24
    assert "output_shape to exactly one capability family" in frame.body
    assert "aggregation_table for a count or grouping" in frame.body
    assert "topology_graph for current instance connectivity or containment" in frame.body
    assert "including a count of queryable relationship or declaration types" in frame.body
    assert "canonical manifest kinds object, interface, link, action, and function" in frame.body
    assert "relationship or relationship type to link" in frame.body
    assert "declared resource type is property_filtered_resources" in frame.body
    assert "runtime resource the operator names is property_filtered_resources" in frame.body
    assert "supplied context rather than an invented identity" in frame.body
    assert "principal_role and purpose are trusted server-bound context" in frame.body
    assert "never use principal_scope or purpose as a clarification_requirement" in frame.body
    assert "empty unresolved_terms and clarification_requirements" in frame.body
    assert "complete principal-scoped set" in frame.body
    assert (
        "evidence_validation request over the principal-scoped visible set is complete"
        in frame.body
    )
    assert "do not ask for a claim identity or narrower subject" in frame.body
    assert "schema inventory question" in frame.body
    assert "complete from the supplied principal-scoped manifest" in frame.body
    assert (
        "current visible connectivity or containment is a complete topology subject" in frame.body
    )
    assert "depend on, route to, connect to, contain, or attach" in frame.body
    assert "whether one observed change preceded an observed regression" in frame.body
    assert "objects or links added, removed, or changed between retained generations" in frame.body
    assert "including independently verified evidence" in frame.body
    assert (
        "MUST use operation validate together with output_shape evidence_validation" in frame.body
    )
    assert "audit the requested answer rather than the subject nouns" in frame.body
    assert (
        "Any requested cardinality, total, count, or grouping MUST use aggregation_table"
        in frame.body
    )
    assert (
        "which objects satisfy an evidence property MUST use property_filtered_resources"
        in frame.body
    )
    assert "whether evidence for a set is sufficient or complete" in frame.body
    assert "does not select members by an evidence property" in frame.body
    assert "Evidence claims, evidence references, verification coverage" in frame.body
    assert "which claims carry evidence references MUST use validate" in frame.body
    assert "selects runtime ontology objects by one readable evidence-valued property" in frame.body
    assert "membership is defined by being added, removed, or changed" in frame.body
    assert "use temporal_comparison even when the requested answer is a list" in frame.body
    assert "membership is defined by a current readable evidence state" in frame.body
    assert "Distinguish declaration inventory from runtime membership" in frame.body
    assert "an explicit count or grouping always uses aggregation_table" in frame.body
    assert (
        "ordinary word incident, issue, degradation, or outage is not an incident_reference"
        in frame.body
    )
    assert "remains explain_change with causal_evidence" in frame.body
    assert "temporal ordering is evidence inside that answer" in frame.body
    assert "ontology objects in the current inventory generation" in frame.body
    assert "principal-scoped ontology declaration inventory" in frame.body
    assert "Finally audit relationship scope" in frame.body
    assert "schema relation between one or two exact supplied ObjectType declarations" in frame.body
    assert "operational runtime traversal and MUST use topology_graph" in frame.body
    assert "generic causal question is complete" in frame.body
    assert "one cause concept and one effect concept" in frame.body
    assert "no unresolved terms or clarification requirements" in frame.body
    assert "requested runtime relation verb dominates ontology nouns" in frame.body
    assert "ontology_manifest only lists declarations" in frame.body
    assert "ontology_declaration for the detail, dependents" in frame.body
    assert (
        "ontology_release_evidence_health for a combined retained-release comparison" in frame.body
    )
    assert "bounded direct impact scope of one selected resource" in frame.body
    assert "Do not reduce this combined schema-and-evidence request" in frame.body
    assert "never invent it, expose it as unresolved, or replace impact traversal" in frame.body
    assert "active Rule semantics from collected Rule references" in frame.body
    assert "declaration_dependents for dependents" in frame.body
    assert "rule_state as its only measure concept" in frame.body
    assert "operation select with ontology_declaration" in frame.body
    assert "Do not reduce either request to ontology_manifest" in frame.body
    assert "instead of clarification" in frame.body
    assert "Do not select that function for instance listing" in frame.body
    assert "query.incident_evidence" in frame.body
    assert "one incident_id and one correlation_id" in frame.body
    assert "without an explicit incident reference is not an incident investigation" in frame.body
    assert "do not require incident_id or correlation_id" in frame.body
    assert "cause_claim_supported=false" in frame.body
    assert "Do not claim a cause" in frame.body
    assert plan.version == 17
    assert "Satisfy the frame's exact output_shape" in plan.body
    assert "ontology_declaration requires query.ontology_declaration" in plan.body
    assert "ontology_release_evidence_health requires both query.ontology_release_diff" in plan.body
    assert "inventory_impact requires query.inventory_impact" in plan.body
    assert "Both nodes are output nodes" in plan.body
    assert "resource target is resolved by trusted server context" in plan.body
    assert "do not substitute topology_at, object_set, resource_list" in plan.body
    assert '"function_name":"query.ontology_declaration"' in plan.body
    assert "declaration_dependents outputs one dependents node" in plan.body
    assert "Every plan node is a declaration output node" in plan.body
    assert "rule_state measure uses the Rule detail node" in plan.body
    assert "aggregation_table requires aggregate" in plan.body
    assert "topology_graph requires topology_at" in plan.body
    assert "use query.manifest as a query.table dependency followed by aggregate" in plan.body
    assert "A matching selector without that predicate is invalid" in plan.body
    assert "names one runtime resource filters the readable name property" in plan.body
    assert "Core builds evidence_validation from the verified principal scope" in plan.body
    assert "For temporal_comparison, create exactly two topology_at source nodes" in plan.body
    assert "baseline-then-current order" in plan.body
    assert "topology.diff, and is the only output node" in plan.body
    assert "preserve every requested readable property and every requested value" in plan.body
    assert "for a requested name, identifier, or label fragment" in plan.body
    assert "Select exists only when the request states no value for that property" in plan.body
    assert (
        "an existence predicate over a required property selects the whole type and never "
        "stands in for a requested value" in plan.body
    )
    assert "A readable property that supplies values accepts only those exact values" in plan.body
    assert "Resolve a requested family, category, class, or group word" in plan.body
    assert "select its listed values with an in predicate" in plan.body
    assert "accepts a contains fragment only when some supplied value already contains it" in (
        plan.body
    )
    assert "never to a value-supplying property" in plan.body
    assert "never pass a family word through as a value" in plan.body
    assert "exactly two metric_scope_series nodes" in plan.body
    assert "MUST NOT contain predicates, traversal, or root_ids" in plan.body
    assert "a principal-scope denial, not a causal plan" in plan.body
    assert "select exact cause and effect concept_id values" in plan.body
    assert "Never invent a resource id or metric concept" in plan.body
    assert "only object_set, function, union" in plan.body
    assert (
        "topology_at, topology_diff, metric_series, metric_scope_series, or evidence_join"
        in plan.body
    )
    assert "depends on exactly one object_set query.table node" in plan.body
    assert "evaluation_time is trusted server-bound context" in plan.body
    assert "object_set source followed by an aggregate node" in plan.body
    assert "Never use query.ontology_relationships for instance listing" in plan.body
    assert '"function_name":"query.incident_evidence"' in plan.body
    assert '"correlation_id":"the exact correlation_id' in plan.body
    assert '"dependency_arguments":{}' in plan.body
    assert "audit the complete closed shape" in plan.body
    assert "exactly one unfiltered visible Resource object_set scope" in plan.body
    assert "Do not output or add query.incident_evidence" in plan.body
