---
title: Live Cockpit Metrics
---
# Live Cockpit Metrics

This document defines the measurement window and denominators for the Live cockpit.
You can distinguish incoming operational activity from control-loop decisions without
mistaking source reads or connection health for execution.

> **Boundary:** These browser measurements never grant execution authority or prove
> runtime readiness. Explicit Sample presentation remains separate from observed Live data.

## Design at a glance

The central SSE feed supplies decoded activity messages. The browser deduplicates them,
retains their original event times, and summarizes a rolling 60-second window independently
of the visible card pool.

| Metric | Included observations | Excluded observations |
|--------|-----------------------|-----------------------|
| Events / sec | Unique control-loop stage and source-read activity messages | Heartbeats, connection metadata, duplicate replay frames |
| Gate mix | Explicit control-loop decisions, once per event | Source reads without a gate decision |
| Tier mix | Explicit control-loop tier assignments, once per event | Source reads without a tier assignment |

## Measurement window

Recent snapshots keep their original observation time. Older snapshots can populate cards
without inflating the current rate. The throughput chart separates control-loop messages
from source reads, and the rate uses two decimal places.

Gate and tier distributions update when an explicit decision or tier is observed, without
waiting for audit completion. Repeated facts do not restart their 60-second window. An
empty distribution says no decision or assignment was observed, not that source reads
were approved.

Each measurement collection retains at most 10,000 entries. Capacity exclusions, invalid
event times, transport gaps, and cursor resets make the window explicitly partial. Freezing
the view preserves its displayed measurements while the bounded collector continues to
receive messages.

## Related docs

| To learn about | Read |
|----------------|------|
| Console surface and source boundaries | [Operator Console](operator-console.md) |
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/interfaces/live-cockpit-metrics.md) |
