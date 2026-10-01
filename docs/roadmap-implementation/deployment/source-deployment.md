# One-Command Source Deployment implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| One entry point and coordinator | in-progress | `scripts/deployment/azure/fdai-up.sh`; `packages/deployment-cli/src/fdai_deployment_cli/source_deploy.py`; `source_azure.py`; `tests/integration/scripts/test_contributor_deployment.py` | Without arguments the wrapper selects `--online` release-kit acquisition. `--source` reaches source mode, and `--signing-key` builds and signs a complete kit before an `--offline-kit` run. The target makes the bare command select source mode and never build a kit. |
| Keyless source Foundation and managed-host handoff | implemented | `source_azure.py`, `source_foundation.py`, `source_genesis.py`, and the focused source tests and 2026-09-29 live `foundation-apply` row in the [CLI ledger](installable-deployment-cli.md) | Source mode reaches a verified Foundation handoff without any key, then stops with `prebuilt_runtime_artifacts_required` and directs the operator to a signed kit. |
| Service image build into the deployment registry | not-started | Owner contract only | `azd-up.sh` builds only Core with `az acr build` for the Container Apps public development path, and `source_image_build.py` builds one selected `dev` service. No five-service source build stage exists in the coordinator. |
| Package-free application continuation | not-started | Owner contract; `source_azure.py` returns `prebuilt_runtime_artifacts_required` | The application stage still consumes kit images, the provider mirror, support wheels, and the Console archive. |
| Keyless Trial initialization by deployment | not-started | Trial storage and resolver in the [licensing ledger](../fork-and-sequencing/capability-licensing.md) | No deployment step writes the first record, no installation identifier exists, and Core composition does not consult the Trial store, so a keyless installation stays observation-only. |
| Key-holder installation entitlement | not-started | `license_issue.py` and `azd-up.sh` issue a 30-day `fdai.license.v1` token bound to the image digest | The no-expiry, installation-bound entitlement is defined in the licensing owner but not implemented. |
| Workstation entitlement-mode selection | in-progress | `license_issue.discover_license_signing_key`; `scripts/deployment/release/check-signing-key.py` | Discovery also reads `FDAI_LICENSE_SIGNING_KEY_FILE` and `~/.config/fdai/license-signing-key.pem`, and an unusable key fails during the application stage instead of before the first Azure effect. |
| Source installation acceptance and teardown | not-started | None | No keyless or key-holder new-subscription receipt and no guarded source-installation teardown exist. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-01 | in-progress | Adopted the ledger with the owner contract after Constitution Article 1 opened the source path to anyone with a clone: no key selects a durable 30-day Trial, the dedicated license key selects a full installation entitlement, and the path builds images in the deployment instead of a signed kit. Earlier source-path provenance stays in the CLI, runtime, Genesis, and licensing ledgers and was not copied. Their kit, appliance, publication, and tenant-build-removal items were superseded and replaced by the ordered plan below. | `current change`; `docs/roadmap/deployment/source-deployment.md`; `docs/roadmap/architecture/fdai-constitution.md`; scope rows above cite the current source | Complete the work packages below in order. |

### Remaining work

- [ ] **WP1 - One entry point.** Make bare `fdai-up.sh` select `fdaictl provision azure --source`
  for its own checkout, remove the wrapper's kit build and `--signing-key` option, and select the
  entitlement mode on the workstation before the first Azure effect. Limit key discovery to
  `secrets/license-signing-key.pem` and the explicit `--license-signing-key` option. Exit: wrapper
  and CLI tests prove that no argument set builds or signs a kit, the bare command reaches source
  mode, and an unusable present key stops with a fixed reason before any Azure call.
- [ ] **WP2 - Source build stage.** Build the five baseline service images from the pinned
  snapshot with the deployment registry's build service, import pinned dependency images, and read
  back every digest. Stop before any service apply when the build service is unavailable. Exit:
  focused coordinator tests with a fake builder prove digest binding, the stop path, and that no
  kit, signature, SBOM, or provenance file is written.
- [ ] **WP3 - Package-free application continuation.** Continue from the source
  `application-plan` checkpoint with the transferred snapshot, lock-file providers from the public
  registry, the WP2 digests, and a source-built Console when selected. Remove the
  `prebuilt_runtime_artifacts_required` redirect. Exit: the source route reaches application
  apply, migrations, catalogs, health, and the second-plan check in focused tests without a kit
  path.
- [ ] **WP4 - Keyless Trial activation.** Add a Terraform-owned installation identifier, pass the
  installation and deployment digests to Core, initialize the Trial record during database
  bootstrap only when none exists, and wire the Trial resolver into Core composition. Exit: focused
  tests prove first-run initialization, rerun and upgrade without renewal, missing-record denial,
  and expiry that blocks acting work while observation continues.
- [ ] **WP5 - Key-holder installation entitlement.** Implement the versioned installation
  entitlement in the [licensing owner](../../roadmap/fork-and-sequencing/capability-licensing.md#key-holder-installation-entitlement),
  issue it on the workstation, and store it through the existing digest-derived Key Vault file
  input. Exit: issuer, Core, and inspector tests prove exact binding, misbinding, unchanged v1
  30-day rejection, and no key material in any output.
- [ ] **WP6 - Acceptance receipts.** From a clean checkout, retain one keyless and one key-holder
  new-subscription `fdai-up.sh` receipt, each with five service digests tagged `sha-<commit>`,
  migrations, health, entitlement mode, Trial end date when applicable, and a second zero-change
  plan. Add a rerun receipt proving the Trial was not renewed and a key-holder rerun that switches
  an existing Trial installation to full entitlement.
- [ ] **WP7 - Guarded teardown.** Add a source-installation teardown that removes only resources the
  installation owns after one typed confirmation and reads back their absence. Exit: focused tests
  and one live teardown receipt.
- [ ] **WP8 - Retire superseded paths.** After WP6, remove `--online` release-kit acquisition and the
  source-mode signed-kit adoption redirect, decide whether `azd-up.sh` is retired or kept as a
  Core-only diagnostic, and update the quickstart and skill. Exit: CLI help and tests expose only
  `--source` and `--offline-kit`, and the documentation names no third installation path.
