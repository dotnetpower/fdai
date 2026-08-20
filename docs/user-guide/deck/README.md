---
title: FDAI Proposal Deck Kit
description: Decision-oriented proposal source for presenting FDAI architecture, safety, value, and adoption.
---

# FDAI Proposal Deck Kit

This kit turns the FDAI story into a decision-oriented proposal. The source documents explain why the operating model should change, how the 15 agents collaborate within fixed safety boundaries, and how an organization can adopt FDAI without enabling changes on day one.

> **Proposal title:** Forward Deployed Agents: An Autonomous Cloud Platform Operated by Agents
>
> **Audience:** Technology executives, cloud platform leaders, SRE, security, FinOps, and governance teams evaluating an FDAI pilot.

## Proposal structure

The proposal follows one fixed agenda. Keep these section names and this order in customer-facing variants:

1. Why cloud operations must change
2. Introducing FDAI
3. Overall architecture
4. Meet the 15 agents
5. How AI agents collaborate
6. Operating scenarios
7. When people step in
8. Areas of operations automation
9. Expected outcomes
10. Demo
11. Adoption approach

## Source files

| File | Slides | Proposal decision |
|------|--------|-------------------|
| [l100-act1-why.md](l100-act1-why.md) | 1-8 | Why change, why FDAI, and whether the architecture is credible. |
| [l100-act2-how.md](l100-act2-how.md) | 9-18 | Whether the agent organization, collaboration model, and human controls are safe. |
| [l100-act3-adopt.md](l100-act3-adopt.md) | 19-26 | What to automate, how to measure value, what to demo, and how to adopt. |

The Korean translations carry the same structure in [l100-act1-why-ko.md](l100-act1-why-ko.md), [l100-act2-how-ko.md](l100-act2-how-ko.md), and [l100-act3-adopt-ko.md](l100-act3-adopt-ko.md).

## Reference files

Use these references to verify technical claims and prepare optional architecture slides that sit outside the fixed 26-slide narrative:

| File | Use when |
|------|----------|
| [ref-ontology-context-vs-rag.md](ref-ontology-context-vs-rag.md) | Comparing ontology context with RAG, explaining how agents reference graph data, or discussing the OWL/RDF and graph-storage choice. |

## How to use the slide briefs

Each slide brief has six fields:

- **Decision question**: The question the slide helps the customer answer.
- **Key message**: The one sentence that should remain after the discussion.
- **On-slide copy**: The minimum copy needed to understand the slide without narration.
- **Visual**: A diagram, comparison, or evidence view. Avoid decorative cards and color bars.
- **Evidence to bring**: Data or artifacts needed before a customer-specific delivery.
- **Presenter note**: Guidance for handling the discussion without turning the proposal into a script.

Use the briefs as proposal source, not as a teleprompter. Remove any statement that cannot be supported by architecture, a demo artifact, or a measured pilot baseline.

## Local delivery artifacts

The tracked Markdown briefs are the public proposal source. Rendered HTML, PowerPoint files, generators, dependencies, screenshots, and demo media stay in an approved delivery copy because they can contain customer-specific framing. Build and review those artifacts only in that delivery workspace.

## Proposal content rules

- **Lead with the operating decision**: Explain the current constraint before introducing an FDAI capability.
- **Separate measured results from targets**: Treat automation rate, incident time, cost reduction, and change lead time as pilot measures until a baseline exists.
- **Make authority visible**: Forseti judges, Thor dispatches, Var carries human approval, Vidar recovers, and Saga audits. No role collapses judgment, approval, execution, and evidence into one identity.
- **Show the safe default**: New capabilities begin in observation mode. Uncertainty, missing evidence, or unavailable approval keeps a change from running.
- **Use generic evidence**: Use synthetic events, resources, screenshots, and identifiers. Never place customer data in this repository.

## Customer workshop inputs

Collect these inputs before adapting the proposal:

| Input | Used in |
|-------|---------|
| Top three recurring operational events | Problem statement and demo scenario. |
| Current approval and rollback path | Human intervention and safety contract. |
| Existing SLO, change, and cost baselines | Expected outcomes and pilot measures. |
| Candidate read-only scope | First adoption phase. |
| Named policy, platform, and security owners | Ownership and promotion review. |

Keep customer-specific values outside the tracked deck sources. Supply them only in an approved delivery copy.

## Quality check

Before publishing a proposal:

1. Confirm that every agenda section has a clear decision outcome.
2. Confirm that all 15 agents and their roles match the pantheon source of truth.
3. Label unmeasured benefits as hypotheses or pilot targets.
4. Confirm that every action example includes a stop condition, rollback, impact limit, dry run, lock, retry key, and audit record.
5. Confirm that observation mode precedes any proposal to enable changes.
6. Run the documentation punctuation, translation, and link checks.

## Next steps

| To learn about | Read |
|----------------|------|
| The 15-agent organization | [Agent pantheon](../../roadmap/agents/agent-pantheon.md) |
| The action safety contract | [Execution model](../../roadmap/decisioning/execution-model.md) |
| Human approval boundaries | [Approvals and channels](../concepts/approvals-and-channels.md) |
| The operator experience | [Operator console](../../roadmap/interfaces/operator-console.md) |
