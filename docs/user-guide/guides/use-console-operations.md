---
title: Work in the operator console
description: What each area of the FDAI console shows you, what you can submit from it, and why a read-only console is a security feature rather than a limitation.
---

# Work in the operator console

The console is where you see what FDAI is doing. It shows incidents, pending approvals, running
processes, scheduled work, provisioning progress, and the evidence behind every decision. What it
never does is change your cloud.

This guide maps the areas you'll actually use, tells you which ones accept a request, and explains
the boundary that makes a browser session safe to leave open.

## The console can't execute

Every panel reads. The console's API client has no create, update, or delete helpers at all, and the
console never receives the executor identity. When you submit something from the console, you are
filing a governed request that re-enters the normal pipeline, not triggering a change.

That design has a practical consequence worth internalizing: **a compromised browser session can't
change your infrastructure**. It can read what that person was allowed to read. Execution authority
lives with the executor identity, which no browser ever holds.

## Where to go for what

| Area | What you do there | Can you submit? |
|------|-------------------|-----------------|
| Overview and live | See current control-plane activity at a glance | No |
| Incidents | Inspect open incidents, their members, timelines, and linked analysis | No |
| Approvals | Review work waiting on a person, with its evidence, quorum, and deadline | Yes, a decision |
| Agent activity and pantheon | Watch which agent is handling what, and inspect agent roles | No |
| Processes | Browse process runs, rendered views, and journal events | Yes, on specific process routes |
| Scheduler runs | Inspect scheduled task dispatch attempts | No, and it can't retry or cancel a task |
| Provisioning | Watch provisioning progress as it streams | No, it never executes provisioning |
| Onboarding and readiness | Check what is still missing before a capability is usable | No |
| Investigations | Start and read bounded Azure investigations | Yes, a read-only investigation |
| Audit and trace | Follow a correlation ID through every recorded step | No |
| Rules, ontology, and promotion gates | Inspect what FDAI knows and what is allowed to run | No |
| Agent oversight | See ownership, human dependencies, and submit an ownership handover proposal | Yes, a proposal |
| Settings | View runtime, model, memory, integration, and identity configuration | Yes, on identity and access |

Approvals is the one place where your click carries a real decision, and even there the decision is
re-authenticated and re-checked on the server before anything runs. See
[Approve a change](approve-change.md) for that flow.

## What the roles get you

The console shows what your role allows and hides the rest, but the server is what actually
enforces it. Every request carries your identity, and the check happens again on arrival.

- **Reader** sees state, evidence, and audit history.
- **Contributor** adds the ability to start a bounded investigation and to author a draft change.
- **Approver** adds approval decisions on work waiting for a person.
- **Owner** adds identity, access, and runtime settings work.

A narrower view in the console is a convenience, not the boundary. Someone who calls the API
directly still gets the same answer, because the capability check doesn't live in the browser.

## Reading a panel honestly

Two habits keep you from over-reading a screen:

- **Check freshness before you trust a number.** Panels project stored state. A quiet incidents list
  can mean a quiet estate, or a projection that hasn't caught up.
- **Treat a missing value as unknown.** The console shows unavailable evidence as unavailable rather
  than filling in a zero, and that distinction is usually the important one during an incident.

## What isn't there yet

A federated Tasks view that gathers work across domains, along with cross-domain projection
metadata, is proposed rather than built. Today you move between the domain areas above rather than
working from one combined queue.

## Next steps

| To learn about | Read |
|----------------|------|
| How to act on work waiting for you | [Approve a change](approve-change.md) |
| How to follow a decision end to end | [Read the audit log](read-audit-log.md) |
| How to ask a bounded question about a resource | [Investigate an Azure resource](investigate-azure-resources.md) |
| Who is accountable behind each agent | [Agent ownership](../concepts/ownership-and-handover.md) |
| Why approvals never travel through the console identity | [Approvals and channels](../concepts/approvals-and-channels.md) |
| The full console contract and route map | [Console operations](../../roadmap/interfaces/console-operations.md) |
