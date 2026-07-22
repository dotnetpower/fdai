# Development Operations Gateway

This Azure Functions project provides a development-only, authenticated gateway from the local
FDAI read API to private Azure resources. It exposes registered operations rather than arbitrary
URLs, ARM paths, commands, or query text.

## Contracts

- Read operations require the configured Contributor group or the FDAI executor principal.
- Write and execute operations require the FDAI executor principal plus idempotency, audit,
  dry-run, stop-condition, rollback, and single-resource impact evidence.
- Resource groups and private probe endpoints come from server configuration.
- The gateway refuses to start unless `FDAI_DEV_GATEWAY_ENABLED=1` and `FDAI_ENV=dev`.
- App Service Authentication validates Microsoft Entra tokens before the anonymous Function route
  runs. Function keys are not an authorization boundary.

## Operations

| Operation | Class | Target |
|-----------|-------|--------|
| `azure.network.nsg.read` | read | One configured development NSG |
| `azure.network.peering.read` | read | Peerings for one configured development VNet |
| `azure.private.http.probe` | read | One server-registered HTTPS private endpoint |
| `azure.network.nsg.rule.upsert` | write | One NSG security rule |
| `azure.network.nsg.rule.delete` | write | One NSG security rule |
| `azure.compute.vm.start` | execute | One VM |
| `azure.compute.vm.deallocate` | execute | One VM |

## Testing

Run the gateway contract tests from the repository root:

```sh
uv run pytest -q --no-cov tests/delivery/dev_operations_gateway
```
