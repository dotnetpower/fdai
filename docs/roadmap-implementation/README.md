# Roadmap implementation ledgers

This directory keeps implementation state separate from normative roadmap design. Each English
ledger mirrors one canonical owner below `docs/roadmap/` and preserves scope, append-only history,
evidence, and observable remaining work.

## Layout

| Roadmap owner | Delivery ledger |
|---------------|-----------------|
| `docs/roadmap/<area>/<name>.md` | `docs/roadmap-implementation/<area>/<name>.md` |

The bilingual roadmap owners link to the same English canonical ledger from `Related docs` or
`관련 문서`. Ledgers do not have Korean copies because implementation history is a stable engineering
record rather than duplicated user-facing design prose.

## Update contract

- Keep normative design, authority boundaries, and public contracts in the roadmap owner.
- Keep current implementation scope and remaining work in the ledger.
- Append material transitions to implementation history without editing recorded rows.
- Cite reviewable repository paths, focused checks, issues, commits, or governed receipts.
- Keep each ledger at or below 400 lines. Split append-only history before exceeding the bound.

## Migration command

The migration command is dry-run by default and writes only after every selected owner plans
successfully:

```bash
python3 scripts/automation/migrate-roadmap-implementation-ledgers.py <owner.md>
python3 scripts/automation/migrate-roadmap-implementation-ledgers.py --apply <owner.md>
```

Use `--all --limit <count>` for bounded batches. Use `--repair-links` to redirect legacy owner
`#implementation-status` references to mirrored ledgers.
