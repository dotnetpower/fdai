---
description: "Use when changing conversation understanding, concept selection, planning, answer composition, answer rendering, or their prompts and catalogs. Forbids lexical meaning, template answers, and silent truncation, and sets the Azure SRE Agent parity bar."
applyTo: "services/core-control-plane/src/fdai/core/conversation/**,services/core-control-plane/src/fdai_core_service/semantic_*.py,services/core-control-plane/src/fdai_core_service/dialogue_relationship.py,services/core-control-plane/src/fdai/delivery/azure/llm/semantic_*.py,services/core-control-plane/src/fdai/delivery/azure/llm/adaptive_answer.py,services/operator-service/src/fdai_operator_service/families/conversation/**,packages/service-contracts/src/fdai_service_contracts/semantic_*.py,rule-catalog/prompts/**/semantic-*.yaml,rule-catalog/prompts/**/conversation-*.yaml,rule-catalog/prompts/**/adaptive-*.yaml,rule-catalog/vocabulary/**,console/src/deck/**"
---

# Conversation Grounding

FDAI answers operational questions through the ontology so that every answer is exact, complete
within its verified scope, and free of hallucination. Retrieval-augmented generation with a frontier
model can sound right while inventing a count, identity, relation, or cause; FDAI must not. The model
understands the question and phrases the answer. The ontology and its verified evidence supply every
operational fact, and deterministic code checks every claim before the operator sees it.

This instruction is the normative policy. The
[Ontology Reasoning Compiler](../../docs/roadmap/interfaces/ontology-reasoning-compiler.md) and
[Ontology Reasoning Coverage](../../docs/roadmap/interfaces/ontology-reasoning-coverage.md) are the
target designs, and the [SRE Agent parity skill](../skills/sre-agent-parity/SKILL.md) is the
comparison procedure. The [natural-language intent routing](architecture.instructions.md#natural-language-intent-routing-must)
rules still apply.

## Meaning from the model, identity from code (MUST)

- A schema-validated model proposes the semantic content of a turn: intent, operation, mentions with
  exact source spans, relation intent, schema concepts and values chosen from complete catalogs, typed
  time values, and follow-up references.
- Deterministic code binds everything that carries identity or authority: the authenticated
  principal, scope, instance identities by exact lookup, result handles, registered LinkTypes, paths,
  and FunctionTypes from reviewed metadata, and exact machine commands. Slash commands and typed API
  commands keep their deterministic path and never pass through natural-language judgment.
- Labels, aliases, and descriptions are context for the model; they are never a lookup table.
- Runtime code MUST NOT derive meaning from regular expressions, keyword, alias, or phrase tables,
  token or substring matching, lexical ranking, or hard-coded utterances. This covers question
  parsing, concept and value resolution, time normalization, and target extraction.
- Code validates each proposal: schema, exact spans, enum membership, catalog identity, domain and
  level fit, typed bounds, and trusted-clock arithmetic. Non-semantic lexing of model output for
  validation is allowed; it never infers the operator's meaning.
- Model unavailability, low confidence, or ambiguity produces a clarification, hold, or typed
  unavailable result, never a lexical fallback.

## Answers from evidence, not templates (MUST)

- An answer to an operational question MUST NOT come from hard-coded prose, canned replies, or string
  templates filled with values. The model authors the answer and its interpretation restatement only
  from verified evidence rows, epistemic statuses, and typed limitation codes.
- The author returns claims as propositions: canonical subject identity, predicate with property or
  LinkType and direction, object or value, polarity, comparator or quantifier, unit or currency,
  temporal basis and time zone, modality or causal class, and rounding. Each surface phrase binds to
  its proposition by exact span, and names compare through canonical identities, never substrings.
- Deterministic claim verification (V-CLAIM) runs before display. It rejects a claim without cited
  evidence, a proposition or literal that differs from its evidence, an undeclared literal, a missing
  required limitation, a count that differs from the authoritative count, an unaccounted result row,
  and a cause claim without causal evidence. An independent model review then checks entailment.
- A failed answer regenerates once with the typed reasons, then holds with the verified evidence
  view.
- Without the model, only reviewed catalog notices for denial, hold, unavailable, and limitation
  states, display labels, accessibility text, exact-command help, and verified evidence tables and
  receipts may render. They MUST NOT state an operational fact beyond the verified data they display.
- Console and Operator renderers display verified values and never author or alter a fact. Rule and
  policy citations required by the LLM quality gate are unchanged.

## Nothing is dropped by a bound (MUST)

- A fixed bound, such as a prompt budget, candidate cap, page size, batch size, evidence reference
  cap, plan size, or rendered row limit, MUST NOT drop items silently.
- Process the complete finite set in successive bounded batches with exact accounting: every item is
  presented, executed, or rendered exactly once, and the processed count equals the total.
- Top-K selection that hides the remaining candidates of a finite catalog is prohibited. Ranked
  retrieval over an open document corpus stays labeled as non-exhaustive.
- Reserve model calls, tokens, and time per stage before a turn starts, and start a batch only when
  its worst case fits. Otherwise return the verified part with a continuation pinned to principal,
  scope, snapshot cutoff, catalog digests, cursor, expiry, and remaining count.
- Automatic continuation stays within a per-turn total ceiling; beyond it the operator resumes
  explicitly. Never present a partial set as complete before its accounting closes.

## Quality bar (MUST)

- Conversation quality is measured against Azure SRE Agent on the same questions, scope, and time,
  comparing the question, the derivation, and the answer side by side in the session browser.
- FDAI must meet the versioned parity rubric in
  [Ontology Reasoning Coverage](../../docs/roadmap/interfaces/ontology-reasoning-coverage.md#sre-agent-parity)
  with zero unsupported claims. Azure SRE Agent output is a comparator, never FDAI evidence.

## Existing violations

Current lexical routing, lexical descriptor ranking, regular-expression target and time extraction,
and template answer renderers are migration debt listed in the coverage plan. Do not add new ones,
and do not extend an existing one to fix a failing question; fix the typed contract, concept
selection, compiler, reader, or composition instead.
