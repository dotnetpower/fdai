---
title: Offline Release Trust Ceremony
summary: Establish and rotate FDAI's public offline-kit trust root without exposing root private keys to CI or operators.
---

# Offline Release Trust Ceremony

Use this runbook to create the first public trust root for disconnected FDAI releases or to rotate
an existing root. The ceremony establishes release authority; it is not a deployment approval and
must never use a test key, repository secret, or operator-supplied root.

> **Current state:** No production root is packaged. Until this ceremony and the client integration
> are complete, `fdaictl provision inspect` correctly reports an offline kit as `candidate` or
> `fail`, never `verified` from file presence alone.

## Roles and prerequisites

Assign named people before scheduling the ceremony:

- **Ceremony coordinator:** Owns the agenda, evidence record, and stop decisions. Does not hold all
  root keys.
- **Root key holders:** Independently control the offline root keys required by the approved root
  threshold. We recommend a threshold of at least two and more key holders than the threshold.
- **Release security reviewer:** Confirms role separation, algorithms, thresholds, expiry, and
  rotation evidence before the public root is merged.
- **Witness:** Records device identifiers, public key fingerprints, times, and deviations without
  handling private key material.
- **Release engineer:** Configures delegated targets, snapshot, and timestamp signing after the root
  is established. This role does not receive a root private key.

Before starting, approve and record:

- TUF specification and Python-TUF major versions.
- Root, targets, snapshot, and timestamp role thresholds and expiry periods.
- Independent offline devices, entropy source, encrypted backup media, and physical custody.
- A recovery policy for lost, compromised, or unavailable key holders.
- A clean, network-isolated ceremony environment and a separate verification device.
- The exact FDAI release and wheel path that will package the public `root.json`.

Stop if a participant, device, approved threshold, expiry, backup destination, or independent
verification device is unavailable.

## Threat controls

| # | Risk | Required control |
|---|------|------------------|
| 1 | A test key becomes production authority | Generate new production keys only during the witnessed ceremony |
| 2 | One person can mint a root | Use the approved multi-key threshold and independent custody |
| 3 | CI receives a root private key | Export only public keys and signed metadata from the offline environment |
| 4 | An operator substitutes a root | Package the public root in the wheel; add no CLI root override |
| 5 | A stale repository freezes clients | Give timestamp and snapshot metadata bounded expiries and monitor renewal |
| 6 | An older signed release rolls clients back | Require monotonically increasing metadata versions |
| 7 | Metadata from different releases is mixed | Use TUF snapshot and timestamp bindings plus exact target hashes |
| 8 | Root rotation locks out clients | Publish roots one version at a time and satisfy both old and new thresholds |
| 9 | A compromised online key becomes permanent | Keep root offline and rotate delegated keys under root authority |
| 10 | A missing artifact escapes review | Retain exact manifest file-set and SHA-256 verification after TUF |
| 11 | A wrong CLI or platform consumes a kit | Keep exact CLI version and platform binding in `OfflineKitManifest` |
| 12 | Symlink or path replacement changes content | Retain no-follow descriptor hashing and regular-file checks |
| 13 | Private material leaks through evidence | Record public fingerprints and signatures only; scan all outputs |
| 14 | A root expires before clients update | Track expiry as a release blocker with an owned renewal window |
| 15 | A ceremony deviation is silently accepted | Stop, preserve evidence, and reschedule unless the approved policy covers it |

## Create the initial root

1. Verify that each offline device is clean, disconnected, time-correct, and observed by the
   coordinator and witness.
2. Each root key holder generates an independent root key on their assigned offline device. Keep
   private keys on that device or approved encrypted backup media. Export only the public key.
3. On the isolated metadata workstation, create initial TUF root metadata with:
   - version `1`;
   - the approved future expiry;
   - all root public keys and the approved root threshold;
   - separate public keys and thresholds for targets, snapshot, and timestamp roles;
   - consistent-snapshot behavior required by the release repository.
4. Move unsigned root metadata to each root key holder through approved media. Each holder verifies
   the complete canonical metadata and signs only after fingerprint and policy comparison.
5. Assemble signatures on the isolated metadata workstation. Verify that the root threshold is met
   and that no unexpected key, role, threshold, extension, or private value is present.
6. On the separate verification device, load the signed metadata with Python-TUF and independently
   verify structure, expiry, version, key ids, role thresholds, and signatures.
7. Produce public ceremony evidence. Hash the signed `root.json`, record public fingerprints,
   thresholds, expiry, Python-TUF version, participants, devices, and verification outcome. Do not
   record private key bytes, PINs, recovery phrases, or encrypted key archives.
8. Create and test encrypted backups under independent custody. Verify restore on an isolated spare
   device, then securely erase temporary private-key copies.

Any signature mismatch, unexpected key, missing threshold signature, malformed metadata, or private
value in the evidence stops the ceremony. Discard the unsigned or partially signed candidate and
restart from approved clean media.

## Package and delegate

1. Add only the verified public `root.json` to the FDAI wheel's package data through a reviewed
   upstream pull request. Pin its SHA-256 in release evidence.
2. Wire `fdaictl provision inspect` to bootstrap Python-TUF from that package resource. Do not add a
   `--release-root`, environment-variable root, network-fetched initial root, or downstream override.
3. Keep targets, snapshot, and timestamp private keys in the approved release signing service. CI
   may access only those delegated online keys and never a root private key.
4. Build each offline kit as a TUF target. Include the FDAI wheel, transitive wheels, signed
   deployment bundle, Terraform binary and provider mirror, OPA, SBOM, and exact-content manifest.
5. Publish versioned root metadata, delegated metadata, and targets through the approved release
   channel. Keep prior public root versions needed for sequential client updates.
6. Build the wheel from a clean checkout. Inspect its contents and confirm it contains the expected
   public root and no private key, test key, signing configuration, or ceremony backup.

## Acceptance drill

Use a disconnected disposable host with no preexisting FDAI trust state:

1. Install the release wheel and inspect a release-signed kit. Require `status=ready`, exit `0`, and
   `artifact.offline-kit=verified` after TUF and exact-content verification.
2. Change one target byte. Require rejection before any artifact executes.
3. Present expired timestamp or snapshot metadata. Require rejection without a clock or expiry
   override.
4. Present an older metadata version after a newer trusted version. Require rollback rejection.
5. Mix metadata or targets from two releases. Require snapshot or hash rejection.
6. Change the CLI version or platform tag. Require compatibility rejection.
7. Add an unlisted file, remove a listed file, and replace an artifact with a symlink. Require
   rejection in every case.
8. Remove all network access and repeat verification. Success must not depend on a public endpoint.

Store sanitized command output, public metadata, artifact digests, and terminal status in the release
evidence record. The drill is complete only if the valid kit passes and every negative case fails.

## Rotate the root

1. Create root version $N+1$ from trusted version $N$. Add or remove keys and update thresholds and
   expiry according to the approved rotation policy.
2. Sign version $N+1$ with enough keys to satisfy the version $N$ root threshold and the new version
   $N+1$ threshold.
3. Publish each intermediate root version. Never skip a version that a deployed client needs.
4. Verify client update from every supported packaged root to the newest root, one version at a
   time, before releasing targets that require the new root.
5. Revoke and destroy retired private keys only after supported clients can update and recovery
   evidence is complete.

For compromise, stop delegated signing, publish no new targets, invoke the approved emergency root
rotation policy, and preserve public forensic evidence. A normal deployment approval cannot waive a
root threshold or metadata expiry.

## Exit criteria

The public offline trust bootstrap is complete only when all items are checked:

- [ ] Initial production `root.json` is threshold-signed and independently verified.
- [ ] Root private keys and backups remain outside source control, CI, cloud secrets, and operator
  workstations.
- [ ] The wheel packages only the verified public root and the CLI has no trust-root override.
- [ ] Delegated signing produces current, expiring targets, snapshot, and timestamp metadata.
- [ ] Valid disconnected verification passes from a clean host.
- [ ] Tamper, expiry, rollback, mix-and-match, wrong-version, wrong-platform, extra-file, and symlink
  drills all fail closed.
- [ ] Sequential root rotation is tested from every supported packaged root.
- [ ] Public ceremony and release evidence is archived with named owners and renewal dates.
