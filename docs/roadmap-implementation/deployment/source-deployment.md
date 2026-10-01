# One-Command Source Deployment implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| One entry point and coordinator | implemented | `scripts/deployment/azure/fdai-up.sh`; `packages/deployment-cli/src/fdai_deployment_cli/{cli.py,entitlement_preflight.py,source_azure.py}`; `test_contributor_deployment.py`, `test_entitlement_preflight.py`, `test_source_azure.py` | Without a mode argument the wrapper deploys its own checkout in source mode from any working directory, builds or signs no kit, and refuses `--signing-key`. Before any Azure call the CLI selects the entitlement from `secrets/integrity-signing-key.pem`, stops on a present but unusable key, and starts `az login` when no session exists. Without `--approval-file` the invocation approves each Foundation checkpoint it shows; those plan contracts refuse every update, replacement, or deletion. The application stage still stops with `prebuilt_runtime_artifacts_required` until WP3. |
| Keyless source Foundation and managed-host handoff | implemented | `source_azure.py`, `source_foundation.py`, `source_genesis.py`, and the focused source tests and 2026-09-29 live `foundation-apply` row in the [CLI ledger](installable-deployment-cli.md) | Source mode reaches a verified Foundation handoff without any key, then stops with `prebuilt_runtime_artifacts_required` and directs the operator to a signed kit. |
| Service image build into the deployment registry | not-started | Owner contract only | `azd-up.sh` builds only Core with `az acr build` for the Container Apps public development path, and `source_image_build.py` builds one selected `dev` service. No five-service source build stage exists in the coordinator. |
| Package-free application continuation | not-started | Owner contract; `source_azure.py` returns `prebuilt_runtime_artifacts_required` | The application stage still consumes kit images, the provider mirror, support wheels, and the Console archive. |
| Keyless Trial initialization by deployment | implemented | `infra/main.tf` `terraform_data.installation`; `standalone_trial_activation.py`; `standalone_host.py`; `standalone_catalog_checkpoint.py`; `runtime/licensing_trial_activation.py`; `test_standalone_trial_activation.py`, `test_installation_anchor.py` | Terraform state owns the installation identifier and first-apply time, so no rerun or upgrade changes them. The AKS application stage gives Core `FDAI_INSTALLATION_BINDING` and `FDAI_LICENSE_DEPLOYMENT_BINDING`, and the managed host runs the Core writer after the application apply and before the initial inventory, recording a digest-bound receipt. The deployment receipt reports `license_mode=trial` only while that read-back window is open under a trusted clock. The Container Apps runtime, which source deployment does not use, does not supply the bindings, and no live first-use receipt exists yet (WP6). |
| Key-holder installation entitlement | implemented | `license_issue.py` (`deployment_license_token`), `standalone_license_installation.py`, `standalone_host.py`, `standalone_application.py`, `ed25519.py`, packaged `upstream-signing-key.pub`, `check-integrity.sh`, `core/licensing/installation_entitlement.py`; `test_standalone_license_installation.py`; [licensing ledger](../fork-and-sequencing/capability-licensing.md) 2026-10-01 rows | The integrity key is now the only licensing key: Core verifies with its packaged copy, the runtime licensing binding and trust package are on the signed framework surface, and the integrity checker rejects every other signed shape. The no-expiry, installation-bound `fdai.installation-entitlement.v1` contract, Core resolution, workstation issuer, and inspector are implemented. On AKS, which source deployment uses, a key-holder deployment issues that entitlement with the installation binding returned by the binding step. The managed host verifies it against both bindings, stores it in the fixed `fdai-capability-license` Key Vault secret, and reads the exact version back. AKS Core then receives it as the CSI-mounted `FDAI_LICENSE_TOKEN`. A Container Apps key holder, which source deployment does not use, still receives the 30-day image-bound v1 token because that runtime supplies no installation binding. No live key-holder receipt exists yet (WP6). |
| Workstation entitlement-mode selection | implemented | `license_issue.discover_license_signing_key`; `entitlement_preflight.select_entitlement_mode`; `scripts/deployment/release/check-signing-key.py` | Discovery reads only the working checkout's `secrets/integrity-signing-key.pem` under the issuer custody rule, the explicit key option and other key paths are removed, and the key scan reports the `integrity` role. The CLI reports the selected mode and stops on a present but unusable key before any Azure call. |
| Trial expiry watermark | not-started | Owner contract only | No Core entitlement-state publication, Operator response stamp, or Console overlay exists, and no watermark path is on the signed framework surface. |
| Source installation acceptance and teardown | not-started | None | No keyless or key-holder new-subscription receipt and no guarded source-installation teardown exist. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-01 | implemented | Completed WP5 deployment issuance for the AKS source path. The deployment binding step now also returns the Terraform installation binding, and the application flow requires it. A key holder deploying to AKS receives the no-expiry installation entitlement instead of the 30-day v1 token. The managed host's `install-license` step accepts either document only against its exact bindings, stores it in the fixed `fdai-capability-license` Key Vault secret, and reads the exact version back. The AKS application stage mounts that secret into Core as `FDAI_LICENSE_TOKEN` through the existing CSI secret environment, which the Core identity can already read. Before this, AKS Core received no installed token of either version. A keyless AKS deployment whose read-back Trial window is open now reports `license_mode=trial` instead of `observation-only`. | `current change`; `test_standalone_license_installation.py` (7 cases: AKS key-holder entitlement, v1 without an installation binding, exact install and readback with no token in the receipt, missing and mismatched installation bindings, the AKS secret environment, and binding-step ordering), two `trial_open` cases in `test_standalone_trial_activation.py`, updated binding fakes; 2,066 deployment CLI cases; Ruff and strict mypy | Retain the live key-holder receipt and the Trial-to-entitlement rerun in WP6. |
| 2026-10-01 | implemented | Completed WP4 for the AKS source path. A `terraform_data.installation` anchor keeps the installation identifier and first-apply time in Terraform state, with `ignore_changes` on the time, and outputs the installation binding and anchor time. The AKS application stage passes the installation binding and the existing deployment-binding digest to Core and stores that digest for the managed host. The new `activate-trial` host step runs the Core writer with the Key Vault state-store DSN after the application apply and before the initial inventory, and the deployment requires its digest-bound receipt. | `current change`; `test_standalone_trial_activation.py` (11 cases: binding digest, anchored command and DSN handoff, recorded rerun, prerequisites, four writer failures, tampered receipt, AKS-only ordering), `test_installation_anchor.py` (2 cases), updated AKS host tests; 2,057 deployment CLI cases; Ruff, strict mypy, `terraform fmt` | Retain the live first-use and rerun receipts in WP6, and supply the bindings on the Container Apps runtime if it ever serves source deployment. |
| 2026-10-01 | in-progress | Implemented the key-holder installation entitlement contract, its Core resolution, the workstation issuer, and `fdaictl license inspect` support. The entitlement grants the complete catalog with no expiry only to the exact distribution, installation, and deployment digests it carries. | `current change`; [licensing ledger](../fork-and-sequencing/capability-licensing.md) 2026-10-01 entitlement row and its tests | Issue it during key-holder deployment and deliver it through the Key Vault file input after WP4 supplies the installation binding. |
| 2026-10-01 | in-progress | Completed the Core half of WP4. Runtime licensing builds the durable Trial store and resolver from the deployment-supplied installation and deployment bindings and the state-store DSN, the execution gate observes it off the event loop, and `python -m fdai.runtime.licensing_trial_activation` opens the window once at the installation's anchored time without renewing a retained record. | `current change`; [licensing ledger](../fork-and-sequencing/capability-licensing.md) 2026-10-01 composition row and its tests | Add the Terraform-owned installation identifier and creation time, pass the installation binding to Core, and invoke the writer during database bootstrap. |
| 2026-10-01 | implemented | Completed WP1. Bare `fdai-up.sh` now deploys its own checkout in source mode from any working directory, builds or signs no kit, and refuses the retired `--signing-key` option. Before any Azure call the CLI selects the entitlement mode from `secrets/integrity-signing-key.pem`, stops with a fixed reason on a present but unusable key, and starts `az login` when no Azure CLI session exists. Without `--approval-file` the invocation approves each Foundation checkpoint it shows and continues, so a run no longer stops for a separate approval file; Foundation and runner-image plan contracts already refuse every update, replacement, or deletion. | `current change`; `test_contributor_deployment.py` (bare command, forwarded modes, refused option, no kit builder), `test_entitlement_preflight.py` (Trial, key holder, three unusable keys, no Azure call before the key check, session reuse, terminal-only login), and the CLI approval assertion in `test_source_azure.py`; 2,039 deployment CLI and 28 wrapper cases pass; Ruff and strict mypy | Implement WP2 and WP3 so the source route reaches the application stage; add the typed delete-or-replace confirmation with the application plans. |
| 2026-10-01 | in-progress | Completed the WP5 key consolidation. Core and the deployment CLI verify every license with the packaged upstream integrity key, and the issuer exception, workstation discovery, release issuer, and `azd-up.sh` read only `secrets/integrity-signing-key.pem`. The `--license-signing-key` option, the environment and home-directory key paths, and the separate license key pair are removed; `check-signing-key.py` reports the `integrity` role. The integrity checker now rejects any signed document that is not exactly the manifest shape, and the runtime licensing binding and trust package joined the signed framework surface. | `current change`; [licensing ledger](../fork-and-sequencing/capability-licensing.md) 2026-10-01 implemented row and its tests | Implement the installation entitlement (rest of WP5) with WP4, then WP9. |
| 2026-10-01 | in-progress | Adopted the ledger with the owner contract after Constitution Article 1 opened the source path to anyone with a clone: no key selects a durable 30-day Trial, the dedicated license key selects a full installation entitlement, and the path builds images in the deployment instead of a signed kit. Earlier source-path provenance stays in the CLI, runtime, Genesis, and licensing ledgers and was not copied. Their kit, appliance, publication, and tenant-build-removal items were superseded and replaced by the ordered plan below. | `current change`; `docs/roadmap/deployment/source-deployment.md`; `docs/roadmap/architecture/fdai-constitution.md`; scope rows above cite the current source | Complete the work packages below in order. |
| 2026-10-01 | in-progress | Added the per-checkpoint approval gate to WP1. `source_azure.py` stops at the runner-image, Foundation apply, runner enrollment, and Foundation state checkpoints for a separate prompt, or returns for an explicit approval file, while Article 1 lets the invocation approve the plan it shows and confirms only deletion or replacement. | `current change`; `packages/deployment-cli/src/fdai_deployment_cli/source_azure.py` | Implement WP1 with the approval change. |
| 2026-10-01 | in-progress | Applied three Owner decisions to the plan through a Constitution Article 1 amendment. The deployment is one command line that also clones the checkout. `secrets/integrity-signing-key.pem` replaces the separate license key pair as the only licensing key. An ended Trial or any other licensing denial shows a persistent Console watermark that no setting, data change, or redeployment hides, whose code joins the signed framework surface. WP1, WP4, and WP5 absorb the key and anchoring changes, and WP9 adds the watermark. | `current change`; owner and [licensing owner](../../roadmap/fork-and-sequencing/capability-licensing.md#trial-expiry-watermark); `check-signing-key.py --scan secrets` reports no integrity role today | Implement WP1 to WP5 and WP9, then retain WP6 receipts. |

### Remaining work

- [x] **WP1 - One entry point.** Make bare `fdai-up.sh` select `fdaictl provision azure --source`
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
  Evidence: the 2026-10-01 WP1 history row and its wrapper, preflight, and CLI tests.
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
- [x] **WP4 - Keyless Trial activation.** Runtime composition consults the Trial store with the
  supplied bindings; `fdai.runtime.licensing_trial_activation` opens the window once at a supplied
  anchored time; Terraform state owns the installation identifier and first-apply time; and the AKS
  source path passes both digests to Core and runs the writer after the application apply. Evidence:
  the 2026-10-01 WP4 rows, `test_standalone_trial_activation.py`, `test_installation_anchor.py`,
  and the Core Trial, resolver, and activation tests in the
  [licensing ledger](../fork-and-sequencing/capability-licensing.md).
- [x] **WP5 - Integrity-key licensing.** The key consolidation is done: Core packages
  `security/integrity/upstream-signing-key.pub` as its verification key, issuance and the
  issuer-workstation check read only `secrets/integrity-signing-key.pem`, the separate license key
  pair is removed, the integrity checker accepts only the manifest shape, and the runtime licensing
  binding, trust verifier, and packaged key are on the signed framework surface. The versioned
  [installation entitlement](../../roadmap/fork-and-sequencing/capability-licensing.md#key-holder-installation-entitlement)
  is also done: its contract, Core resolution, workstation issuer, and inspector pass exact-binding,
  misbinding, cross-protocol, and secret-free output tests. A key-holder AKS deployment issues it
  with the installation binding that WP4 supplies, stores it in the fixed `fdai-capability-license`
  Key Vault secret with exact readback, and mounts that secret into AKS Core as
  `FDAI_LICENSE_TOKEN`. Evidence: the 2026-10-01 WP5 rows, `test_standalone_license_installation.py`,
  and both `test_installation_entitlement.py` files.
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
