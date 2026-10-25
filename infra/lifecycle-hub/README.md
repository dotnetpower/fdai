# Lifecycle Hub deployment

Deploy the customer's Lifecycle Hub as its own bundled UI/API and PostgreSQL database.
This root doesn't deploy Release Hub or FDAI, and needs no vendor URL, tenant, identity or state.

## Files

| Path | Purpose |
|------|---------|
| `main.tf` | Customer product selection, provider, backend and outputs |
| `variables.tf` | Deployment-specific inputs and optional login/catalog bindings |
| `tests/standalone.tftest.hcl` | Offline mock plans for this product |
| `../modules/hub-service/` | Shared resource implementation, instantiated for this product only |

Use the same root for development and production with separate private input files and backend
state locations. The default native local backend requires an explicit absolute private state
path; remote backend selection is a reviewed Terraform override, not an environment flag.
`target` is the existing internal Lifecycle Hub token; it doesn't select an environment.
An existing registry is an input; this root doesn't adopt or create it.

## Deployment

Follow the [single-product procedure](../modules/hub-service/README.md) with:

```bash
ROOT=infra/lifecycle-hub
TARGET=target
```

For an existing running Hub, follow the
[staged upgrade procedure](../modules/hub-service/README.md#upgrade-an-existing-running-hub).
Keep `image` on the new candidate and temporarily set `app_image` to the approved existing
serving digest. After verified migration, set `app_image=null` to activate the candidate.
Omitting `app_image` preserves the existing single-image behavior.
Optional `custom_domain` binds a public HTTPS subdomain and optional Azure DNS records while
updating the runtime origin and probe `Host` headers.

Omit `catalog` until you explicitly connect an approved source. No remote directory lookup or
catalog request occurs at standalone startup. Catalog operations report unavailable.
After standalone migration, use the explicit `bind-catalog --actor ... --reason ...` application
command with a separately approved source configuration before serving with that binding.
Binding a key doesn't approve an export pin or download catalog bytes.

Without `operator_auth`, management APIs return 503 and the UI explicitly shows unavailable
functionality. Anonymous management API policy is deferred, not a blocker for independent
startup/UI preparation. A later UI/readiness-only deployment requires separate explicit
authorization and isn't acceptance of anonymous management functionality. No Azure deployment
is claimed.

For a separately approved Agent-capable image, `operator_auth.agent_principals` accepts explicit
`installation_id`, `object_id` and `client_id` bindings. The shared module forwards nonempty
bindings to the runtime; an empty list omits the field so older images keep their existing
configuration. Release Hub rejects Agent bindings. This input neither grants `Agent.Access` nor
creates federation, namespace RBAC or an installation record. A bound installation's signed
enrollment is submitted separately through the
[operator enrollment API](../../lifecycle/hub/README.md#explicit-remote-development-profile).

## Existing installations

Don't apply this root over existing resources with an empty state. First follow the backed-up,
product-specific [ownership transfer](../modules/hub-service/README.md#existing-state).
The existing `infra/hubs-development` root remains unchanged for its current owners.

## Related docs

| To learn about | Read |
|----------------|------|
| Customer deployment contracts | [Hub-Managed Lifecycle](../../docs/roadmap/deployment/hub-managed-lifecycle.md) |
| Configuration ownership | [Lifecycle Configuration](../../docs/roadmap/deployment/lifecycle-configuration.md) |
