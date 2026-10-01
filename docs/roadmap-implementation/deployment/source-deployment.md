# One-Command Source Deployment implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| One entry point and coordinator | in-progress | `scripts/deployment/azure/fdai-up.sh`; `packages/deployment-cli/src/fdai_deployment_cli/source_deploy.py`; `source_azure.py`; `tests/integration/scripts/test_contributor_deployment.py` | Without arguments the wrapper selects `--online` release-kit acquisition. `--source` reaches source mode, and `--signing-key` builds and signs a complete kit before an `--offline-kit` run. Source mode also stops at four Foundation checkpoints for a separate `genesis_approval_prompt.py` prompt, or for an explicit `--approval-file` when noninteractive, which Article 1 does not allow. The target makes the bare command select source mode and never build a kit. |
| Keyless source Foundation and managed-host handoff | implemented | `source_azure.py`, `source_foundation.py`, `source_genesis.py`, and the focused source tests and 2026-09-29 live `foundation-apply` row in the [CLI ledger](installable-deployment-cli.md) | Source mode reaches a verified Foundation handoff without any key, then stops with `prebuilt_runtime_artifacts_required` and directs the operator to a signed kit. |
| Service image build into the deployment registry | not-started | Owner contract only | `azd-up.sh` builds only Core with `az acr build` for the Container Apps public development path, and `source_image_build.py` builds one selected `dev` service. No five-service source build stage exists in the coordinator. |
| Package-free application continuation | not-started | Owner contract; `source_azure.py` returns `prebuilt_runtime_artifacts_required` | The application stage still consumes kit images, the provider mirror, support wheels, and the Console archive. |
| Keyless Trial initialization by deployment | in-progress | `runtime/licensing.py`; `runtime/licensing_trial_activation.py`; `PostgresTrialStore`; [licensing ledger](../fork-and-sequencing/capability-licensing.md) 2026-10-01 composition row | Core composition consults the Trial store when the deployment supplies `FDAI_INSTALLATION_BINDING`, `FDAI_LICENSE_DEPLOYMENT_BINDING`, and the state-store DSN, and the anchored activation writer exists. No deployment step creates the installation identifier or anchored creation time, passes the installation binding, or invokes the writer, so a keyless installation stays observation-only. |
| Key-holder installation entitlement | in-progress | `license_issue.py`, `ed25519.py`, packaged `upstream-signing-key.pub`, `check-integrity.sh`; [licensing ledger](../fork-and-sequencing/capability-licensing.md) 2026-10-01 row | The integrity key is now the only licensing key: Core verifies with its packaged copy, the runtime licensing binding and trust package are on the signed framework surface, and the integrity checker rejects every other signed shape. Deployment still issues a 30-day `fdai.license.v1` token bound to the image digest; the no-expiry, installation-bound entitlement is not implemented. |
| Workstation entitlement-mode selection | in-progress | `license_issue.discover_license_signing_key`; `scripts/deployment/release/check-signing-key.py` | Discovery reads only the working checkout's `secrets/integrity-signing-key.pem` under the issuer custody rule, the explicit key option and other key paths are removed, and the key scan reports the `integrity` role. An unusable key still fails during the application stage instead of before the first Azure effect. |
| Trial expiry watermark | not-started | Owner contract only | No Core entitlement-state publication, Operator response stamp, or Console overlay exists, and no watermark path is on the signed framework surface. |
| Source installation acceptance and teardown | not-started | None | No keyless or key-holder new-subscription receipt and no guarded source-installation teardown exist. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-01 | in-progress | Completed the Core half of WP4. Runtime licensing builds the durable Trial store and resolver from the deployment-supplied installation and deployment bindings and the state-store DSN, the execution gate observes it off the event loop, and `python -m fdai.runtime.licensing_trial_activation` opens the window once at the installation's anchored time without renewing a retained record. | `current change`; [licensing ledger](../fork-and-sequencing/capability-licensing.md) 2026-10-01 composition row and its tests | Add the Terraform-owned installation identifier and creation time, pass the installation binding to Core, and invoke the writer during database bootstrap. |
| 2026-10-01 | in-progress | Completed the WP5 key consolidation. Core and the deployment CLI verify every license with the packaged upstream integrity key, and the issuer exception, workstation discovery, release issuer, and `azd-up.sh` read only `secrets/integrity-signing-key.pem`. The `--license-signing-key` option, the environment and home-directory key paths, and the separate license key pair are removed; `check-signing-key.py` reports the `integrity` role. The integrity checker now rejects any signed document that is not exactly the manifest shape, and the runtime licensing binding and trust package joined the signed framework surface. | `current change`; [licensing ledger](../fork-and-sequencing/capability-licensing.md) 2026-10-01 implemented row and its tests | Implement the installation entitlement (rest of WP5) with WP4, then WP9. |
| 2026-10-01 | in-progress | Adopted the ledger with the owner contract after Constitution Article 1 opened the source path to anyone with a clone: no key selects a durable 30-day Trial, the dedicated license key selects a full installation entitlement, and the path builds images in the deployment instead of a signed kit. Earlier source-path provenance stays in the CLI, runtime, Genesis, and licensing ledgers and was not copied. Their kit, appliance, publication, and tenant-build-removal items were superseded and replaced by the ordered plan below. | `current change`; `docs/roadmap/deployment/source-deployment.md`; `docs/roadmap/architecture/fdai-constitution.md`; scope rows above cite the current source | Complete the work packages below in order. |
| 2026-10-01 | in-progress | Added the per-checkpoint approval gate to WP1. `source_azure.py` stops at the runner-image, Foundation apply, runner enrollment, and Foundation state checkpoints for a separate prompt, or returns for an explicit approval file, while Article 1 lets the invocation approve the plan it shows and confirms only deletion or replacement. | `current change`; `packages/deployment-cli/src/fdai_deployment_cli/source_azure.py` | Implement WP1 with the approval change. |
| 2026-10-01 | in-progress | Applied three Owner decisions to the plan through a Constitution Article 1 amendment. The deployment is one command line that also clones the checkout. `secrets/integrity-signing-key.pem` replaces the separate license key pair as the only licensing key. An ended Trial or any other licensing denial shows a persistent Console watermark that no setting, data change, or redeployment hides, whose code joins the signed framework surface. WP1, WP4, and WP5 absorb the key and anchoring changes, and WP9 adds the watermark. | `current change`; owner and [licensing owner](../../roadmap/fork-and-sequencing/capability-licensing.md#trial-expiry-watermark); `check-signing-key.py --scan secrets` reports no integrity role today | Implement WP1 to WP5 and WP9, then retain WP6 receipts. |

### Remaining work

- [ ] **WP1 - One entry point.** Make bare `fdai-up.sh` select `fdaictl provision azure --source`
  for its own checkout, remove the wrapper's kit build and `--signing-key` option, and select the
  entitlement mode on the workstation before the first Azure effect. Read only the fixed
  `secrets/integrity-signing-key.pem`, report its integrity role in `check-signing-key.py`, and
  start the interactive `az login` when no Azure CLI session exists, so the one-line
  `git clone ... && fdai/scripts/deployment/azure/fdai-up.sh --region <region>` works from any
  directory. Let the invocation approve each plan it shows by binding the exact plan digest
  internally, and keep one typed confirmation only for deleting or replacing an existing resource,
  replacing the per-checkpoint prompts and the noninteractive `--approval-file` requirement. Exit:
  wrapper and CLI tests prove that no argument set builds or signs a kit, the bare command reaches
  source mode, a run that deletes or replaces nothing advances through every checkpoint without an
  approval file, and an unusable present key stops with a fixed reason before any Azure call.
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
- [ ] **WP4 - Keyless Trial activation.** The Core half is done: runtime composition consults the
  Trial store with the supplied bindings, and `fdai.runtime.licensing_trial_activation` opens the
  window once at a supplied anchored time. Add a Terraform-owned installation identifier and
  creation time, pass the installation and deployment digests to Core, and invoke that writer
  during database bootstrap at the anchored creation time. Exit: focused tests prove first-run
  initialization, rerun and upgrade without renewal, a deleted record re-created with its original
  activation time, missing-record denial, and expiry that blocks acting work while observation
  continues.
- [ ] **WP5 - Integrity-key licensing.** The key consolidation is done: Core packages
  `security/integrity/upstream-signing-key.pub` as its verification key, issuance and the
  issuer-workstation check read only `secrets/integrity-signing-key.pem`, the separate license key
  pair is removed, the integrity checker accepts only the manifest shape, and the runtime licensing
  binding, trust verifier, and packaged key are on the signed framework surface. Remaining:
  implement the versioned installation entitlement in the [licensing owner](../../roadmap/fork-and-sequencing/capability-licensing.md#key-holder-installation-entitlement),
  issue it on the workstation, and store it through the existing digest-derived Key Vault file
  input. Exit: issuer, Core, and inspector tests prove exact binding, misbinding, unchanged v1
  30-day rejection, no key material in any output, and that an entitlement never verifies as a v1
  token or a manifest and the reverse.
- [ ] **WP6 - Acceptance receipts.** From a clean checkout, retain one keyless and one key-holder
  new-subscription `fdai-up.sh` receipt, each with five service digests tagged `sha-<commit>`,
  migrations, health, entitlement mode, Trial end date when applicable, and a second zero-change
  plan. Add a rerun receipt proving the Trial was not renewed and a key-holder rerun that switches
  an existing Trial installation to full entitlement and removes the watermark.
- [ ] **WP7 - Guarded teardown.** Add a source-installation teardown that removes only resources the
  installation owns after one typed confirmation and reads back their absence. Exit: focused tests
  and one live teardown receipt.
- [ ] **WP8 - Retire superseded paths.** After WP6, remove `--online` release-kit acquisition and the
  source-mode signed-kit adoption redirect, decide whether `azd-up.sh` is retired or kept as a
  Core-only diagnostic, and update the quickstart and skill. Exit: CLI help and tests expose only
  `--source` and `--offline-kit`, and the documentation names no third installation path.
- [ ] **WP9 - Trial expiry watermark.** Publish the Core-resolved entitlement state with its
  observation time, stamp every authenticated Operator API response with the latest state, and
  render the [watermark](../../roadmap/fork-and-sequencing/capability-licensing.md#trial-expiry-watermark)
  on every Console route in English and Korean, treating a missing or stale state as not activated.
  Add the watermark component, the Operator stamp, and their state contract to the signed
  framework surface. Exit: focused Core, Operator, and Console tests with a controlled clock prove
  the watermark for an ended Trial, a missing record, a rejected token, and a stale state; its
  absence for an active Trial and a full entitlement; that no configuration, environment,
  database, role, or preference value hides it; and a Playwright check shows it above dialogs
  without blocking input.
