---
name: sre-agent-parity
description: "Compare FDAI ontology answers with Azure SRE Agent answers on the same question, scope, and time through the operator's session browser. Use when the operator asks for SRE Agent parity, SRE Agent comparison, SRE 에이전트 비교, or validation that FDAI answers at least as well as Azure SRE Agent. Captures the question, each derivation process, and each answer, establishes independent ground truth, scores parity rubric v1, and records redacted runs."
argument-hint: "Name the question batch, cohort, or question IDs to compare"
---

# Azure SRE Agent Parity

FDAI must answer operator questions at least as well as Azure SRE Agent, and without hallucination.
Azure SRE Agent answers with a frontier model and live Azure tools; FDAI answers from the ontology
and verified evidence. This skill runs matched comparisons that show where FDAI is better, equal, or
worse, and turns every loss into a general fix.

This skill is procedure only. The policy is
[conversation-grounding.instructions.md](../../instructions/conversation-grounding.instructions.md),
and parity rubric v1 and the M2 gate are normative in
[Ontology Reasoning Coverage](../../../docs/roadmap/interfaces/ontology-reasoning-coverage.md#sre-agent-parity).
Redacted run records extend the
[comparison ledger](../../../docs/internals/sre-agent-comparison-ledger.md).

## Preconditions

- **Authorization**: The Owner's request names the exact subscription and resource groups to compare,
  or a disposable test scope. Stop when the scope is unnamed.
- **Same scope, read-only**: The Azure SRE Agent covers that scope with read-only role assignments and
  no action approval, and FDAI's inventory covers the same scope. Record any difference.
- **No actions**: Never approve, run, or schedule an action from either product during a comparison.
- **Operator sign-in**: The operator signs in to the Azure SRE Agent portal and the FDAI Console in the
  session browser. Never type, read, store, or transmit credentials or tokens, and never inspect
  cookies, browser storage, or authorization headers.
- **Budgets**: At most 10 questions per batch, a five-minute per-question deadline, a 60-minute total
  deadline, a 15-minute no-progress deadline, and the SRE Agent usage ceiling that the Owner set.
- **Build identity**: Record the FDAI source revision, active prompt profiles, and ontology release.

## Workflow

1. **Freeze the batch**: Record question IDs, wording, locale, answer contract, and the truth query or
   adjudication method before asking either product.
2. **Ask Azure SRE Agent**: Open the agent at `https://sre.azure.com`, start a new chat thread, and
   submit the exact question. Wait up to the per-question deadline for a terminal answer.
3. **Capture its derivation**: Read the visible steps, including tools called, queries shown,
   resources read, and clarifications, plus the elapsed time and the final answer.
4. **Ask FDAI**: In a new FDAI Console conversation, submit the same wording right after the SRE Agent
   run. Capture the restatement, selected concepts, plan summary, evidence receipts, epistemic
   statuses, claims, answer, latency, and model calls.
5. **Pin the truth**: Run the frozen read-only truth query immediately after both answers, or have a
   reviewer who did not author the question adjudicate. When the relevant state changed between the
   two runs, record the question as inconclusive. Truth never comes from either product's answer.
6. **Score both answers**: Score all eight criteria of parity rubric v1 for each product and mark any
   unsupported or invented claim as a hard failure.
7. **Record the run**: Append a redacted run record with the rubric version to the ledger.
8. **Classify every loss**: Assign understanding, concept selection, compiler, reader, evidence, or
   composition as the root cause, and link the general fix. Recheck the original question and at
   least three paraphrases after the fix.

Each product answers each question once per parity run. FDAI stability is measured separately by the
repeated L1 cohort runs.

## Evidence handling

- **Private capture**: Raw answers, derivations, and screenshots stay in the session and in an ignored
  local evidence path with owner-only permissions. Delete them after the redacted record is written,
  or after 30 days at the latest.
- **Redaction first**: Replace tenant identifiers, subscription identifiers, resource names,
  endpoints, and personal data before any text enters the ledger, an issue, a pull request, or a
  report. Never send raw captures to a third-party service.
- **No evidence import**: Azure SRE Agent output never becomes FDAI evidence, a fixture, or gold truth.

## Stop rules

- Rerun a question only with a new hypothesis, recorded as a new run that links to the earlier one.
- A timeout or portal failure records an inconclusive result, not a loss or a win.
- Stop the batch on throttling, a sign-in prompt, an unrecordable scope mismatch, or any sign that the
  browser path would disclose raw tenant data outside the private capture.

## Related

| To learn about | Read |
|----------------|------|
| Conversation policy and the quality bar | [conversation-grounding.instructions.md](../../instructions/conversation-grounding.instructions.md) |
| Parity rubric v1, the M2 gate, and assurance cohorts | [Ontology Reasoning Coverage](../../../docs/roadmap/interfaces/ontology-reasoning-coverage.md) |
| Prior matched runs and the 120-question catalog | [Comparison ledger](../../../docs/internals/sre-agent-comparison-ledger.md) |
| FDAI conversation assurance campaigns | [Conversational assurance skill](../conversational-assurance/SKILL.md) |
