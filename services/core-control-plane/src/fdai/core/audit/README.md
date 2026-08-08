# `src/fdai/core/audit`

Append-only, hash-chained audit log. Every terminal path (execute, HIL reject,
timeout, abstain, deny) writes an entry. Source of truth for the KPI dashboard.
