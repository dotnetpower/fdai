# `src/aiopspilot/core/executor`

Executor. Holds the only privileged workload identity; applies idempotent actions
under a per-resource lock. Adapters in `delivery/` render the abstract action.
