# Development Operations Gateway

This Azure Functions project provides a development-only, authenticated gateway from the local
FDAI read API to private Azure resources. It exposes registered operations rather than arbitrary
URLs, ARM paths, commands, or query text.

## Contracts

- Read operations require the configured Contributor group or the FDAI executor principal.
- Write and execute operations are enabled in the upstream development deployment. Only the
  configured FDAI executor principal can call them. The caller first invokes
  `azure.operation.plan`; the gateway validates the registered operation, bounded scope, and
  arguments plus the idempotency, audit, stop-condition, rollback, and impact evidence, then
  confirms the target through a bounded reader-identity ARM GET and stores a five-minute one-time
  dry-run receipt in private Blob storage. The matching mutation consumes that receipt with ETag
  compare-and-swap before ARM is called.
- Retrying the same plan returns the same unconsumed receipt. A consumed or expired plan requires a
  new idempotency key, so refreshes cannot create multiple simultaneously valid receipts for one
  mutation intent.
- Mutation idempotency keys are claimed in a private, Microsoft Entra-authenticated Blob
  container before Azure is called. A completed duplicate reuses the recorded response, a
  conflicting payload is blocked, and storage uncertainty fails closed. Stale pending claims can
  be recovered with ETag compare-and-swap after the bounded claim timeout.
- Mutations acquire a 60-second Blob lease on the target resource before ARM submission. Different
  idempotency keys therefore cannot mutate the same VM or NSG rule concurrently.
- ARM `202 Accepted` responses remain `submitted`, and the server-issued status URL stays private
  in the operation record. The executor can poll it only through `azure.operation.status` with the
  original idempotency key.
- ARM `429` responses honor a bounded `Retry-After` delay for at most three attempts. Mutation
  `5xx` responses aren't blindly retried because provider acceptance may be ambiguous.
- Resource groups and private probe endpoints come from server configuration.
- Private probe configuration rejects literal IP addresses, localhost, fragments, credentials,
  and control characters before any token is requested. Probe requests never follow redirects.
- The gateway refuses to start unless `FDAI_DEV_GATEWAY_ENABLED=1` and `FDAI_ENV=dev`.
- App Service Authentication validates Microsoft Entra tokens before the anonymous Function route
  runs. Function keys are not an authorization boundary.

## Operations

| Operation | Class | Target |
|-----------|-------|--------|
| `azure.network.nsg.read` | read | One configured development NSG |
| `azure.network.peering.read` | read | Peerings for one configured development VNet |
| `azure.private.http.probe` | read | One server-registered HTTPS private endpoint |
| `azure.operation.plan` | mutation dry run | One registered mutation payload |
| `azure.network.nsg.rule.upsert` | write | One NSG security rule |
| `azure.network.nsg.rule.delete` | write | One NSG security rule |
| `azure.compute.vm.start` | execute | One VM |
| `azure.compute.vm.deallocate` | execute | One VM |
| `azure.operation.status` | execute status | One previously submitted mutation |

Mutation callers use this sequence:

1. Call `azure.operation.plan` with `operation_id` and the exact mutation `arguments`.
2. Put the returned `dry_run_receipt` in the mutation's `safety` envelope with its idempotency,
  audit, stop-condition, rollback, and single-resource evidence.
3. Submit the registered mutation. A changed payload, expired receipt, or second consumption is
  rejected before ARM. Poll `azure.operation.status` by idempotency key when the mutation returns
  `submitted`.

## Testing

Run the gateway contract tests from the repository root:

```sh
uv run pytest -q --no-cov tests/delivery/dev_operations_gateway
```
