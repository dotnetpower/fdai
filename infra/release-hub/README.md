# Release Hub deployment

Deploy the vendor's Release Hub as its own bundled UI/API and PostgreSQL database.
This root doesn't deploy Lifecycle Hub or FDAI, and takes no customer Hub input.

## Files

| Path | Purpose |
|------|---------|
| `main.tf` | Vendor product selection, provider, backend and outputs |
| `variables.tf` | Deployment-specific network, capacity, registry and optional login inputs |
| `tests/standalone.tftest.hcl` | Offline mock plans for this product |
| `../modules/hub-service/` | Shared resource implementation, instantiated for this product only |

Use the same root for development and production with separate private input files and backend
state locations. The default native local backend requires an explicit absolute private state
path; remote backend selection is a reviewed Terraform override, not an environment flag.
The `release` internal token is a product, not a release channel or environment.
An existing registry is an input; this root doesn't adopt or create it.

## Deployment

Follow the [single-product procedure](../modules/hub-service/README.md) with:

```bash
ROOT=infra/release-hub
TARGET=release
```

For an existing running Hub, follow the
[staged upgrade procedure](../modules/hub-service/README.md#upgrade-an-existing-running-hub).
Keep `image` on the new candidate and temporarily set `app_image` to the approved existing
serving digest. After verified migration, set `app_image=null` to activate the candidate.
Omitting `app_image` preserves the existing single-image behavior.

Login is optional for process startup. Without `operator_auth`, management APIs return 503 and
the UI explicitly shows unavailable functionality. Anonymous management API policy is deferred,
not a blocker for independent startup/UI preparation. A later UI/readiness-only deployment
requires separate explicit authorization and isn't acceptance of anonymous management functionality.
This change has local evidence only, not an Azure deployment receipt.

### Catalog export and freshness

Lifecycle Hubs pull the signed catalog export from `GET /v1/catalog/export`. The Release Hub
never pushes to a customer installation. By default the request needs a bearer token for a
service identity that `operator_auth.service_object_id` admits.

| Input | Effect |
|-------|--------|
| `operator_auth.public_catalog_export = true` | Serves the signed, content-free export without a bearer token, so a Lifecycle Hub can use `access = "anonymous"`. Omitted or `false` keeps token-required access. Only the Release Hub accepts it. |
| `timestamp_renewal_check_seconds` | Automatically renews the freshness of already published content. `0` (default) disables it; otherwise `60` to `3600`. It publishes no new content. |

Set `public_catalog_export` only when the export carries no content you need to protect. The
signature protects integrity, not confidentiality. Without it, a Lifecycle Hub configured for
`access = "anonymous"` can't read the export. Each new field is written to the Hub configuration
only when set, so an older image keeps parsing an unchanged configuration. Adoption settings
(`review` or `auto`, and their expiring authorization) belong to each
[Lifecycle Hub deployment](../lifecycle-hub/README.md#pull-only-catalog-adoption).

## Existing installations

Don't apply this root over existing resources with an empty state. First follow the backed-up,
product-specific [ownership transfer](../modules/hub-service/README.md#existing-state).
The existing `infra/hubs-development` root remains unchanged for its current owners.

## Related docs

| To learn about | Read |
|----------------|------|
| Vendor release contracts | [Lifecycle Releases and Channels](../../docs/roadmap/deployment/lifecycle-releases-and-channels.md) |
| Lifecycle architecture | [Hub-Managed Lifecycle](../../docs/roadmap/deployment/hub-managed-lifecycle.md) |
