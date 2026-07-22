---
title: SRE Runbooks
description: Customer-neutral operator procedures and templates for incident response, recovery, and governed automation.
---

# SRE Runbooks

These runbooks turn FDAI's SRE contracts into repeatable operator procedures.
Upstream documents the required safety checks, evidence, decisions, and terminal
outcomes. A downstream fork supplies environment-specific commands, resource
names, owners, paging integrations, and rollback implementations.

## Incident operations

| Procedure | Use it when |
|-----------|-------------|
| [Incident triage](incident-triage.md) | A new incident needs scope, severity, ownership, and investigation |
| [SLO burn response](slo-burn-response.md) | Multi-window error-budget burn raises a detected issue |
| [RCA evidence collection](rca-evidence-collection.md) | An investigation needs a bounded, cited evidence set |
| [Incident mitigation and rollback](incident-mitigation-and-rollback.md) | A response plan proposes a governed change |
| [Postmortem workflow](postmortem-workflow.md) | A resolved incident needs review and follow-up |

## Preparedness

| Procedure | Use it when |
|-----------|-------------|
| [Deep DB-DR restore drill](db-dr-drill.md) | PostgreSQL restore evidence must be refreshed |
| [Chaos game day](chaos-game-day.md) | A promoted fault scenario is exercised |
| [Alert tuning](alert-tuning.md) | Noise, misses, or stale routing need measured correction |

## Governance and setup

- [Exemption workflow](exemption-workflow.md)
- [Entra app registration](entra-app-registration.md)

## Required runbook contract

Every executable procedure defines owner and approver, bounded scope, preflight,
stop conditions, rollback, evidence, audit reference, and terminal no-op behavior.
If any required item is unavailable, stop and route to review.
