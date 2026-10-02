# FDAI Governed Chaos Provider

This optional extension binds the existing governed Chaos execution seam to deployment-owned
durable state for the scenario lab. It registers the `fdai.governed_chaos` entry point named
`catalog-scenario`.

The package adds no authority. Promotion, human approval, recovery dispatch, independent evidence,
and target selection remain deployment records that the provider reads and validates.

## Configuration

Set these environment variables only in the protected scenario-lab runtime:

| Variable | Purpose |
|----------|---------|
| `FDAI_STATE_STORE_DSN` | PostgreSQL state store DSN used by existing FDAI durable adapters. |
| `FDAI_GOVERNED_CHAOS_PROMOTION_LEDGER` | Reviewed JSONL scenario promotion ledger path. |
| `FDAI_GOVERNED_CHAOS_TARGET_BINDING_ID` | Opaque scenario-lab binding id expected by prepared run plans. |

Optional prefix variables can narrow where approval, plan, dispatch, and recovery-evidence records
are stored. The defaults are documented in `fdai_governed_chaos_provider.config`.

## Testing

Run `uv run pytest -q --no-cov extensions/governed-chaos-provider/tests`.
