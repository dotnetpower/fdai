# Two-Hub development boundaries

This independent Terraform root prepares a vendor Release Hub and a customer Target Lifecycle
Hub in one test subscription. It is a development validation path, not the source installer,
the first-installation offline package, a production catalog, or an FDAI workload deployment.
No Azure deployment or live identity/database validation accompanies this change.

## Boundaries and prerequisites

Each Hub has its own resource group, VNet, ACA Environment, PostgreSQL server/database,
managed identity, private Key Vault/DNS, NAT egress address, and Log Analytics workspace.
There is no VNet peering. Database and vault public access are disabled.
Vault network ACLs also default to deny without a trusted-service bypass. Both databases
explicitly enable connection/checkpoint logging, connection throttling, and a TLS 1.2 floor;
applications and migration Jobs wait for those settings. Same-apply managed-identity role
assignments declare `ServicePrincipal` to avoid directory-replication lookup races.
Resource groups alone do not establish isolation; live network and authorization denial
checks remain required before claiming the boundary works.

Resource-local Trivy annotations for `AZU-0021` and `AZU-0026` cover its retired-server-field
mapping, not missing controls. Flexible Server uses `connection_throttle.enable` and
`ssl_min_protocol_version`; the focused
[security regression](../../tests/integration/infra/test_hubs_development_security.py) requires
both real settings for each Hub, alongside logging, default-deny ACLs, and startup ordering.
Checkov uses resource-local annotations for Azure-managed delegated/private-endpoint subnets
(implicit outbound access disabled), its unrecognized `for_each` vault-to-endpoint graph edge
(the same regression checks the explicit endpoint wiring), and the development-only
seven-day, single-region backup policy. These are not a production NSG or geo-redundant
disaster-recovery claim; no scanner-wide exclusions are added.

Vendor HTTPS ingress permits approved operator CIDRs and the customer NAT address. Customer
ingress permits operator CIDRs only. Every business API independently verifies Entra RS256
access tokens, issuer, audience, tenant, time, and principal bindings. ACA principal headers
grant no authority. Operator delegated scope/client/OID allowlists and customer service
identity/app-role authorization are separate. The service can only read the vendor export.
The vendor identity has no customer API, DB, or vault grant.

Required inputs are intentionally not committed:

| Input | Requirement |
|-------|-------------|
| Subscription, tenant, location, prefix | Exact approved dedicated test scope and region |
| Operator IDs and CIDRs | Explicit Entra object IDs and bounded browser source networks |
| Database administrator | Approved human Entra database bootstrap administrator |
| Registry and images | Existing approved registry plus independently built digest-pinned images |
| Release public key | Independently approved development Ed25519 public PEM, never a private key |
| Secret versions | Version IDs only, after out-of-band provisioning |

Private network bootstrap access to each VNet, Entra application/admin-consent permissions,
role-assignment permission, provider registration, regional quota, and a cost/cleanup decision
are also required. This root deliberately creates no privileged bootstrap VM or shared
cross-boundary network.

## Design, critique, and revision

Initial design: enable remote listeners and let a Target Hub fetch an export from the vendor.
Critique: an ACA header is not authentication; a digest beside a download is not trust;
ephemeral SQLite and signing keys cannot survive replica replacement; two RGs are not isolation.
Revised design: explicit remote entrypoint, direct bearer validation, independent operator pin
approval, durable PostgreSQL trust/revision state, versioned secret references, separate
identities and private data planes. New capabilities stay development-only and do not enable
an installation agent transport or apply a Plan.

## Provisioning sequence after separate execution approval

Do not execute these stages under code-delivery authorization alone.

1. **Review the exact preview.** Select the inputs above and a private, access-controlled Terraform
   state backend. Review the cost and exact `terraform plan` with both enable flags false.
   Planning requires Azure/Entra access and was not run here.
2. **Create boundaries only.** Apply the separately approved plan with `enable_apps=false` and
   `enable_migration_jobs=false`. Verify private DNS and the two independent bootstrap paths.
3. **Provision independent development keys.** Use the existing key generators on a trusted
   private bootstrap host outside the checkout. Never paste keys into chat, shell arguments,
   logs, Terraform variables/state, image layers, or a browser. For example:

   ```bash
   umask 077
   uv run --project lifecycle/release-hub fdai-release-hub dev-init "$PRIVATE_DIR/release"
   uv run --project lifecycle/hub fdai-lifecycle-hub dev-keygen "$PRIVATE_DIR/target.pem"
   ```

   These commands create independent Ed25519 private files with mode `0600`; the parent directory
   must be private and outside source control. Do not overwrite an existing signing key.
   Provision each private PEM as its own vault's `development-signing-key` through an approved
   file-based upload with value output disabled. Supply only the vendor public PEM as
   `release_public_key`, verified through the customer's separate trust channel.
   This is not a production root ceremony. Key rotation requires a separate reviewed migration.
4. **Bootstrap service-owned database roles.** From each private network as the approved Entra
   database administrator, use PostgreSQL's `pgaadauth_create_principal_with_oid` for that
   Hub's managed identity object ID (`service` principal type). Make only its own database and
   `public` schema owned by that role; revoke `CONNECT` and schema creation from `PUBLIC`.
   Do not grant either identity access to the other server/database.
   Provision a passwordless SQLAlchemy URL in that vault's `hub-database-url`:
   `postgresql+psycopg` driver, own role/database/host, port 5432, and `sslmode=verify-full`.
   The CA store must validate Azure's certificate. The app gets fresh tokens using only its
   own managed identity, with no developer/CLI credential fallback.
5. **Migrate explicitly.** Set the actual secret version IDs, then enable only
   `enable_migration_jobs`. Review/apply the exact change. Each manual-only ACA Job runs
   `python -m fdai_lifecycle_hub.remote migrate` with its own identity and private DB secret.
   Creating the Job does not execute it: request and run exactly one approved execution per Hub.
   Require success and schema revision 1 before enabling apps. Migrations take a PostgreSQL
   advisory transaction lock and reject unknown revisions; they do not reset existing data.
   An older Target Hub layout needs a separate explicit data migration, not `create_all` repair.
6. **Enable applications.** Review/apply `enable_apps=true` only after migration evidence.
   Images run as UID 10001 with the bundled UI; no writable local state is authoritative.
   `/healthz` is liveness; `/readyz` checks database schema readiness. Both expose no business
   data. The explicit remote profile alone binds port 8080; default local CLIs remain loopback.
7. **Validate and replace a replica.** Complete the acceptance checks below, replace an ACA
   revision/replica, and repeat persistence/denial checks before calling the setup validated.

The app startup refuses missing configuration, signing key, unverified TLS, password DSNs,
or an unmigrated database. It does not generate a key or silently create remote tables.
Expected startup, identity, and storage failures produce sanitized errors, not DSN/token output.

## Independent trust approval and bounded import

The customer operator obtains the exact export revision and SHA-256 through an independently
approved authenticated review channel, separate from the download, its ETag, or its supplied
digest. The Target Hub Catalog import screen requires that operator to submit the pin, reason,
and exact `approve <revision> <digest>` confirmation through its authenticated approval API.
The API binds the audit actor to the verified Entra OID, never a browser-supplied identity.

Only then can the operator request one outbound import. The configured HTTPS URL and customer
managed identity are fixed in the approved deployment configuration. Redirects and compression
are rejected; maximum export size is 8 MiB, socket timeout five seconds, total import transport
deadline fifteen seconds, without retries or automatic polling. Existing exact-byte manifest
signatures, expiry, and recall parsing remain authoritative. Approval changes during download,
wrong keys, changed same-revision bytes, and revision rollback cannot update accepted state.

Pin approval, accepted export bytes/digest, public-key digest, revision floor, and attributed
audit events persist in the customer DB. Planning revalidates the accepted export under a lock,
including elapsed download/lock time for expiry. This generates a Plan only for an already
enrolled, approved, ownership-proven, managed synthetic installation with suitable artifact
evidence. Publishing a manifest alone never proves an artifact exists.

## Build and validate locally

From the repository root, build each image with the
[digest-pinned Buildx procedure](../modules/hub-service/README.md#freeze-one-candidate).
It supplies the required approved `NODE_IMAGE`, `PYTHON_IMAGE` and `UV_IMAGE` digest references;
the Dockerfile has no unpinned fallback bases.

| Image | `TARGET` | `IMAGE_TAG` |
|-------|----------|-------------|
| Vendor | `release` | `fdai-release-hub:dev` |
| Customer | `target` | `fdai-target-hub:dev` |

Then validate the UI and retained Terraform root:

```bash
npm --prefix lifecycle/hub/ui run build
npm --prefix lifecycle/release-hub/ui run build
npm --prefix lifecycle/hub/ui run test:browser
terraform -chdir=infra/hubs-development init -backend=false
terraform -chdir=infra/hubs-development validate
```

`Dockerfile.hubs.dockerignore` allowlists source/manifests/UI; it excludes keys, env files,
local databases, dependency trees, and prebuilt UI output. Runtime images contain no deployment
configuration or keys. The build has optional `OFFLINE_DEPS=true` named contexts:
`hub-dependencies` is a wheelhouse for the frozen lock export plus `hatchling==1.31.0`;
`hub-npm-cache` is a cache populated by both UI lockfiles. Runtime wheels are installed with
the frozen export's hashes. This supports network-isolated image validation without disabling
TLS verification; it is unrelated to FDAI's signed offline installation package.
Local image evidence was collected on native `linux/arm64`. An approved image for the selected
ACA runtime architecture must still be built, published and verified; neither a local tag nor
Terraform's digest-format check proves that registry artifact exists.

Opt-in real image smoke tests:

```bash
FDAI_TEST_RELEASE_HUB_IMAGE=fdai-release-hub:dev \
FDAI_TEST_TARGET_HUB_IMAGE=fdai-target-hub:dev \
uv run --project lifecycle/release-hub --with pytest --with pytest-cov \
  python -m pytest -q --no-cov -c /dev/null lifecycle/hub/tests/test_hub_images.py
```

They use task-owned containers/volumes, no Docker network or published/shared ports, real
loopback HTTP UI/assets/API checks, and restart persistence. Browser tests use built assets
and synthetic intercepted APIs at desktop/constrained widths, not live Entra. PostgreSQL tests
must use the isolated validation server on 5433 through
`scripts/automation/with-local-test-database.py`, never runtime 5432 or a remote DSN.

## Live acceptance and remaining limits

After separate execution approval, verify: approved operator sign-in; unauthenticated and wrong
operator/audience/service denial; synthetic registration/signing/publication/channel addition;
independently approved import; synthetic enrollment, approval, ownership, management, and Plan;
tamper, expiry, rollback, same-revision conflict and wrong-key rejection; recall exclusion;
replica replacement persistence; cross-DB and cross-vault network and identity denial.
Keep tokens, keys, and DSNs out of captured evidence. Preserve both data stores before cleanup.
Key Vault purge protection intentionally prevents immediate permanent deletion.

Static Terraform validation is not a cloud preview, network isolation test, Entra consent test,
registry artifact check, or deployment result. Production TUF roles/freshness/key ceremonies,
automatic polling, registry mirroring, Agent apply/roll-off, ARM64 Core image follow-up #2167,
and a complete FDAI installation are outside this development path.

## Related docs

| To learn about | Read |
|----------------|------|
| Local vendor workflow | [Release Hub](../../lifecycle/release-hub/README.md) |
| Installation planning | [Lifecycle Hub](../../lifecycle/hub/README.md) |
| Architecture and remaining delivery | [Hub-managed lifecycle](../../docs/roadmap/deployment/hub-managed-lifecycle.md) |
