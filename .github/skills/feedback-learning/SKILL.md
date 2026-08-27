---
name: feedback-learning
description: "Classify corrective feedback into the smallest durable FDAI artifact without bloating always-loaded instructions. Use when the operator asks to capture a learning, a repeated agent mistake needs prevention, or a temporary observation needs bounded follow-up."
argument-hint: "Describe the correction or reusable learning"
---

# Bounded Feedback Learning

Capture corrective feedback only when it can prevent a repeat failure. Prefer executable evidence
over prose, and store each learning in one authoritative destination.

## Choose One Destination

| Destination | Use when | Example |
|-------------|----------|---------|
| No persistence | The feedback is a one-time preference or already documented | Use the requested response format for the current turn only. |
| Regression or property test | A behavior can be falsified automatically | A tool description must not tell the parent agent to stop after a delegated call. |
| Design or contract | The learning changes authority, public behavior, schemas, or subsystem boundaries | Record a new approval invariant in the owning design before implementation. |
| Scoped instruction | A short rule must apply automatically to a file pattern | Add a four-line source convention to the existing path-scoped instruction. |
| On-demand skill | A substantial, reusable procedure has multiple steps | Document how to diagnose one CI job without polling or rerunning it. |
| Learning inbox | The observation is credible but lacks enough evidence for a durable rule | Record a bounded topic until another occurrence confirms or disproves it. |

Do not copy the same learning into a test, instruction, skill, and inbox. Link from secondary
artifacts when discovery requires it.

## Workflow

1. State the correction as an observable before-and-after behavior.
2. Identify the evidence that proves the correction is general rather than incidental.
3. Search existing tests, designs, instructions, and skills for an authoritative home.
4. Select the smallest destination from the table.
5. If the destination is durable, remove any superseded inbox entry in the same change.
6. Run the narrowest existing check for the destination and report what was captured.

## Learning Inbox

Use [`.github/learnings/`](../../learnings/) only when evidence is not yet strong enough for a test,
design, instruction, or skill. Follow its README entry format and limits.

- Keep at most 10 active topics and 8 KB of active entry content.
- Use one topic file per independently reviewable observation.
- Read only entries whose declared scope matches the current task.
- Give every entry a review condition. Use a date only when the evidence truly expires with time.
- Promote, merge, or remove an entry when its review condition is met.
- Never treat an inbox entry as authority to change runtime behavior, permissions, approval, or
  execution mode.

## Safety Boundaries

- Corrective feedback is evidence, not authority.
- Never persist secrets, tenant values, prompts, raw logs, or customer identifiers.
- Never weaken a safety gate to encode a convenience preference.
- A repeated safety or contract defect belongs in an executable test and the owning design.
- Do not create a global instruction when path routing or an on-demand skill is sufficient.
