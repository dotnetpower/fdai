# `src/fdai/core/executor`

Executor. Holds the only privileged workload identity; applies idempotent actions
under a per-resource lock. Adapters in `delivery/` render the abstract action.

`ThorExecutionPort` is the Core-owned injection contract for PR-native,
direct-API, and tool-call execution. `InProcessThorExecutionPort` binds the
existing executor instances without adding transport, changing authority, or
duplicating Saga audit, Vidar recovery, shadow, lock, or idempotency state.
