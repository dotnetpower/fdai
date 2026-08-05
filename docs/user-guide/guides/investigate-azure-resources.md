---
title: Investigate an Azure resource
description: How to ask FDAI a bounded, read-only question about an Azure resource, and how to read the evidence it returns.
---

# Investigate an Azure resource

When something looks wrong with a resource, you usually need a few specific facts before you can
decide anything: what state it's in, who changed it last, whether the platform itself was healthy.
FDAI answers those questions from a fixed catalog of bounded investigations that read Azure and
never change it.

This guide covers what you can ask, what the answer contains, and how to read a result that comes
back as something other than a clean answer.

> **Read-only by construction:** An investigation collects evidence. It can't authorize or execute
> an Azure change, and the identity it reads with is separate from the executor identity. Nothing on
> this page can turn into a change on its own.

## What you can investigate

The catalog is fixed and versioned. Each entry is owned by Heimdall, the detection agent, and
declared as read work, so a new investigation can't quietly introduce a write.

| Investigation | Answers |
|---------------|---------|
| Resource state | What state is this resource in right now, such as whether a VM is running? |
| Change attribution | Who or what made this control-plane change? |
| Resource change history | Which operations ran against this resource recently? |
| Platform health | Was Azure itself healthy for this resource, or was the platform the problem? |
| Guest shutdown | Do the guest logs show the operating system shutting down? |
| Network security | Which security-group rules and associations apply, and what is open? |
| Network peering | What is the peering topology, and is it in sync? |

Each entry maps to one versioned query plan, so the same question asked twice runs the same bounded
query instead of whatever a model happened to generate.

Example: a VM stops responding at 02:14. You check resource state to confirm it's deallocated, then
change attribution to see whether a person or an automation deallocated it, then platform health to
rule out an Azure-side event.

## What a result tells you

An investigation returns evidence, not a conclusion. Every result carries the context you need to
judge how much weight it deserves:

- **Status**, so you can tell a real answer from an unavailable one.
- **Which resource** the evidence is about, resolved to an exact reference.
- **When it was observed**, along with a freshness indication.
- **Whether it was truncated**, and why, so a partial list never reads as a complete one.
- **Evidence references** you can follow into the audit trail.
- **Limitations**, when the source couldn't answer completely.

Read the observation time before you act on the content. A correct answer about five minutes ago is
still an answer about five minutes ago.

## When the answer isn't a straight answer

Three outcomes matter more than the happy path, because each one changes what you're allowed to
conclude.

| Outcome | What happened | What to do |
|---------|---------------|------------|
| Ambiguous | The name you gave matches several resources | Pick from the candidate list that comes back, then ask again |
| Unavailable | The provider call failed or was throttled | Treat the fact as unknown, and don't read it as healthy |
| Truncated | The result hit a bound | Narrow the time window or the scope before drawing a conclusion |

The ambiguous case stops early on purpose. Rather than guessing which `app-db` you meant and running
a history query against the wrong one, FDAI returns the candidates and waits.

The unavailable case is the one worth internalizing. A failed health query is not evidence of
health. FDAI marks the source unavailable and records the limitation without the raw provider error,
so a telemetry outage can never be summarized as a working workload.

## How to start one

Investigations run through the Operator API:

```http
POST /read-investigations
```

The route is registered only when your deployment configures investigations. Starting one needs the
Contributor role or higher. Reader can see results but can't start an investigation, because even a
read against a live subscription is worth attributing to a person.

You can reach the same catalog conversationally as well. Asking in chat routes to the same bounded
plans and returns the same evidence, so the conversational path never gets a wider view of Azure
than the API has.

## What this doesn't do

- **It doesn't prove reachability.** Security-group rules and peering state tell you what is
  configured. Confirming that traffic actually flows takes further evidence, such as effective rules
  and route checks, which are separate steps.
- **It doesn't diagnose.** An investigation returns facts. Turning facts into a cause is
  [root-cause analysis](../sre/root-cause-analysis.md), which reasons over this evidence and stays a
  cited hypothesis rather than an instruction.
- **It doesn't expand on its own.** Broader resource discovery, provider profiles, and generated
  command explanations are design work rather than something you can use today.

## Next steps

| To learn about | Read |
|----------------|------|
| How investigations fit into incident work | [Triage and investigation](../sre/triage-and-investigation.md) |
| How evidence becomes a cited cause | [Root-cause analysis](../sre/root-cause-analysis.md) |
| How a detected issue reaches you in the first place | [Observability, detection, and forecasting](../sre/observability-detection-and-forecasting.md) |
| How to trace an investigation in the evidence trail | [Read the audit log](read-audit-log.md) |
| The full investigation contract and query plans | [Azure read investigations](../../roadmap/interfaces/azure-read-investigations.md) |
