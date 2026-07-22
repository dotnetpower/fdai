---
title: Postmortems and Learning
description: How FDAI builds an evidence-backed postmortem draft and turns lessons into governed improvement candidates.
---

# Postmortems and Learning

A postmortem explains impact, chronology, causes, response, recovery, and
follow-up without rewriting the audit record. FDAI can build a deterministic
template from incident and audit data, then optionally enrich it through a
configured postmortem model.

## Draft contents

- Incident summary and verified impact.
- Ordered audit timeline and lifecycle transitions.
- Grounded root cause and contributing factors.
- Actions taken, approvals, rollback, and recovery evidence.
- What worked, what failed, and unresolved limitations.
- Corrective and preventive follow-up with owners.

If an optional model is unavailable, the generator still returns the
template-based draft. It does not fabricate missing impact or cause.

## Preserve evidence boundaries

The postmortem references audit rows and citations; it does not mutate them.
Human edits remain distinct from machine records. Missing evidence is marked
unavailable, and unresolved hypotheses remain hypotheses.

## Learning loop

The learning extractor can identify recurring correlation keys, root causes,
successful action types, overrides, rollbacks, and human approval patterns. These become
inert candidates for rules, runbooks, or knowledge entries.

A candidate must carry provenance and pass schema, review, regression, shadow,
and promotion gates. The learning loop never edits the active catalog directly.

## Review workflow

1. Confirm incident scope, severity, and verified impact.
2. Reconcile the audit timeline with external evidence.
3. Separate root cause from contributing factors and detection gaps.
4. Record rollback and recovery outcomes, including remaining impact.
5. Assign follow-up owners and measurable completion evidence.
6. Submit reusable lessons through the governed catalog or runbook workflow.

## Next steps

| To learn about | Read |
|----------------|------|
| How incidents close | [Incident management](incident-management.md) |
| How RCA stays grounded | [Root-cause analysis](root-cause-analysis.md) |
| How to reconstruct decisions | [Read the audit log](../guides/read-audit-log.md) |
| The postmortem procedure | [Postmortem workflow runbook](../../runbooks/postmortem-workflow.md) |
