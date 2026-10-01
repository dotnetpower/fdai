---
title: Capability Licensing
---
# Capability Licensing

A downstream distribution often reaches its customer as an image, not as source: the fork is built,
the image is handed over, and it runs inside a network the publisher cannot reach. This document
defines how such a distribution activates entitlement without shipping a secret, without a network
call, and without ever becoming a path to higher autonomy.

> **Scope:** The mechanism is upstream and identical for every distribution. The public key is a
> distribution artifact, and the token is deployment configuration. This document does not define
> commercial terms, pricing, or a revocation service.

## Design at a glance

The naive shape - bake a serial number into the image at build time - fails immediately. An image is
a tar file, so anything embedded in a layer is readable by whoever receives it. That also
contradicts the secret contract in
[security-and-identity.md](../architecture/security-and-identity.md), which allows secrets only
through the environment or a mounted secret.

Licensing therefore inverts the asymmetry, reusing the pattern the repository already applies to the
framework-surface manifest and the offline kit:

| Where | What | Why it is safe there |
|-------|------|----------------------|
| Inside the image (read-only) | the **public** verification key | a public key is not a secret; publishing it costs nothing |
| Outside the image (deployment config) | the **signed license token** | one ASCII string in an environment variable or mounted secret, unforgeable without the private key |

A read-only root filesystem is not an obstacle, because no activation state is ever written into the
image. The token arrives through the normal secret path, and any durable record belongs in the state
store.

## Durable keyless Trial target

The [one-command source deployment](../deployment/source-deployment.md) will initialize one 30-day
Trial at first activation through an authenticated deployment writer during database bootstrap.
The activation time is anchored to the installation's Terraform-owned creation time, so a run that
finds the record missing re-creates it with that original time instead of opening a new window.
Its installation and deployment bindings are independent from
the source revision and image digest, so an ordinary upgrade or restart cannot renew the Trial.
The activation time never changes. Every durable observation advances a revision and the
last-observed UTC time; a clock regression creates a persistent blocked state, not another Trial.
The first observation at or after expiry blocks new acting requests without stopping observation,
diagnosis, audit, export, or safety-required in-flight completion and recovery.

One resolver turns a committed, installation-bound record into an entitlement, and the shared
license entitlement authority consults it wherever a token grants no acting capability. Every
execution path already resolves through that authority, so PR-native, direct-API and tool-call
paths inherit the same answer rather than each carrying a Trial check.

A Trial substitutes for an absent or lapsed token and never rescues one that was rejected,
misbound, or not yet valid, so malformed or expired signed credentials create no Trial fallback.
Read-only capability stays unconditional, so an ended window blocks new acting work while
observation, diagnosis, audit, and export continue. Absence, a record bound to another
installation, a detected clock regression, an observation older than the moment being decided,
and unreachable storage each deny rather than grant. Missing or inconsistent retained records
never open a new window: the runtime denies, and only a deployment run re-creates a missing record
at its anchored activation time.

The store commits observations with a compare-and-set on the complete previous revision. Core
composition consults it whenever the deployment supplies `FDAI_INSTALLATION_BINDING`,
`FDAI_LICENSE_DEPLOYMENT_BINDING`, and the state-store DSN. Each acting decision observes the store
in a worker thread, away from Core's event loop, and an invalid or incomplete binding composes no
Trial. The writer `python -m fdai.runtime.licensing_trial_activation` opens the window at the
supplied anchored time, keeps a retained record unchanged, and refuses a record bound to another
installation. Supplying the installation binding and invoking that writer during deployment
bootstrap are still open, so a keyless installation remains observation-only until both land.

The [key-holder installation entitlement](#key-holder-installation-entitlement) removes the Trial
restriction for one installation; the signed-token 30-day ceiling stays for every token that
travels to another operator. A signed offline package authenticates artifacts, not usage rights.
It removes Trial only when a separately valid entitlement accompanies it. Publisher private keys
never enter the deployment. A source owner who also
controls all persistent state can remove these checks; this offline mechanism does not claim
tamper-proof enforcement or global reinstall detection.

## Trial expiry watermark

An ended Trial must be visible, not only enforced. Like the activation notice of an unactivated
desktop operating system, the Console then shows a persistent watermark on every view.

- **When it shows:** whenever licensing withholds the acting capability `operations.typed-mutation`
  or the Console has no current entitlement state. That covers an ended Trial, a missing or
  misbound record, a rejected or expired token, a detected clock regression, and unreachable Trial
  storage. Only an active Trial, the issuer workstation, or an entitlement that grants the acting
  capability hides it.
- **What it shows:** a localized two-line notice in the lower-right corner, above all content and
  dialogs, stating that the evaluation period has expired or that FDAI is not activated, and that
  observation continues while acting work is unavailable. It is semi-transparent, passes pointer
  input through, cannot be dismissed, and is exposed to assistive technology.
- **How it travels:** Core publishes its resolved entitlement state with the observation time, and
  the Operator API stamps every authenticated response with the latest state. The Console renders
  the watermark from whichever response arrives, so blocking one endpoint cannot hide it, and a
  missing or stale state renders it.
- **No off switch:** No configuration, environment variable, feature flag, database value, role,
  Console preference, or fork composition seam hides it.
- **Tamper evidence:** The Console watermark, the Operator stamp, the runtime licensing binding, and
  the packaged verification key belong to the signed framework surface. Changing them changes the
  surface digest, and only the upstream integrity key can sign a new manifest, so verifying an
  installation's source or images against the signed manifest exposes the change.

The watermark is an availability notice. It neither grants nor removes authority, and its absence
proves nothing: the shared execution ceiling still decides every acting request.

## Issuer workstation exception

**Initial design.** Treat the presence of any private-key file under `secrets/` as proof that the
runtime is on the issuer workstation, then skip licensing.

**Critique.** A filename is not a cryptographic identity. An empty file, an unrelated key, a
symlink, or a mounted key path would satisfy a presence check.

**Revised design.** A source checkout may enter `issuer-workstation` status only when every check
below passes:

- the execution venue is `local` and the asset root has a Git checkout marker;
- the fixed `secrets/integrity-signing-key.pem` path is a current-UID, mode-`0600` regular file
  read through a bounded, nonblocking, no-follow descriptor; and
- the file contains an Ed25519 private key whose derived public bytes exactly match the tracked
  upstream integrity public key `security/integrity/upstream-signing-key.pub`, which Core
  packages as its only license verification key.

**Owner decision (2026-10-01).** The upstream integrity signing key is the only licensing key and
replaces the separate license key pair. One
compromise domain now covers framework integrity and licensing: the key holder can re-sign the
framework surface and issue every token and entitlement, and a key rotation requires re-issuing
all of them. Domain separation keeps each signature to one purpose: the integrity verifier accepts
only the manifest shape, and each license verifier accepts only its own `schema_version`, so a
signature made for one never verifies as the other.

The runtime does not open the private-key path in a deployed venue. The Docker build context excludes
the complete `secrets/` tree. A verified issuer workstation ignores any configured license token and
keeps the full catalog available, while all promotion, RBAC, risk, approval, rollback, audit, and
effect-verification gates remain unchanged. Missing, malformed, incorrectly permissioned, or
mismatched private-key material grants no exception and does not stop observation.

This proves possession of the integrity key, not attachment to immutable physical hardware. Copying
the key copies issuer status. A later hardware-backed key design can strengthen that custody boundary
without changing the signed token contract.

## Key-holder installation entitlement

The issuer-workstation exception covers only a local runtime. A key holder who deploys to Azure
needs the same full availability in a venue that must never read the private key.

**Initial design.** Issue the existing 30-day full-catalog token on every key-holder deployment.

**Critique.** The key holder's own installation then falls back to read-only 30 days after the
last deployment, which is a Trial under another name. Binding the image digest also makes every
upgrade depend on a new issuance, and a longer v1 window would weaken the ceiling that protects
tokens issued to other operators.

**Revised design.** Deployment tooling issues a separately versioned installation entitlement:

- It is issued only on a workstation that passes the same integrity-key checks as the issuer
  exception. The runtime still never opens a private key.
- A new `schema_version` keeps the document domain-separated from the v1 token and the integrity
  manifest, and the integrity key signs it.
- It grants the complete shipped catalog of the expected distribution.
- It requires exact installation and deployment binding digests and carries no image digest and
  no `not_after`, so upgrades and restarts keep it valid.
- It travels like a token: a Key Vault file input under a digest-derived secret name, bound by
  Core at startup.
- Any binding mismatch resolves to `misbound`, and the v1 30-day ceiling stays unchanged for
  every token that leaves the key holder's own installations.

The entitlement has no revocation path other than replacing the deployment's secret reference. It
is acceptable only because it is useless outside the installation it binds.

## The token

The token is `base64url(canonical-document) "." base64url(signature)` - a single ASCII string that
fits an environment variable, a Container Apps secret, or a Kubernetes Secret mount. The signature
covers the exact canonical document bytes, so field order cannot be reinterpreted, and
`schema_version` inside the document keeps the payload domain-separated from every other FDAI
signature. That matters because the same key also signs the framework-surface manifest, which
carries no `schema_version`.

| Claim | Purpose |
|-------|---------|
| `license_id`, `distribution_id` | identify the entitlement and the distribution that issued it |
| `capability_ids` | which catalog capabilities this license makes available |
| `not_before`, `not_after` | the validity window |
| `image_digest` | optional binding to one runtime image |
| `tenant_binding` | optional binding to one deployment, as a **digest only** |

The issuer accepts validity periods from 1 through 30 days and defaults to 30 days. The Core token
contract and offline inspector also reject a signed validity window longer than 30 elapsed UTC
days, so an alternate issuer cannot bypass the ceiling. Renewal issues a new token rather than
extending or rewriting an existing signed document.

The shipped Core runtime binds `distribution_id` to `fdai-upstream`. A signature made by the same
issuer for another distribution is still `misbound` here. A downstream distribution supplies its
own expected identity at composition; an environment value cannot relabel a token after issuance.

`tenant_binding` is never a tenant identifier. Binding by digest keeps the repository, the image, and
every log line free of customer values
([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).

## The rule that makes this safe

**A license moves the `available` axis only.** It can never promote a capability out of shadow,
widen a role, relax a risk decision, or grant approval authority. Those stay with the promotion
registry, RBAC, and the risk gate
([coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)).

The consequence is worth stating plainly: a trusted token can remove one availability hold, but it
cannot authorize an effect by itself. An action still needs every independent promotion, role,
risk, approval, identity, safeguard, and effect-verification decision. A licensing check that could
replace or raise any of those decisions would itself be a backdoor.

Entitlement is also an intersection with the shipped catalog, so a token cannot invent a capability
the distribution does not implement.

**Read-only capabilities are not licensed.** Every degraded status already grants them
unconditionally, so an `active` license grants them too, whether or not it lists them. Without this,
a license naming only acting capabilities would leave an operator seeing strictly less than an
expired license would, and renewing an entitlement could remove dashboards. The available set of an
`active` license is therefore always a superset of the degraded set.

## Handling the token

The token is not a secret in the sense the private key is - it cannot be forged - but it **is** a
bearer credential. A license issued without an `image_digest` or a `tenant_binding` works for anyone
who can read it. The issuer therefore writes it owner-only and never through a symlink, and a
distribution that expects tokens to travel should bind them. File output contains only the canonical
token bytes, without a trailing newline, because surrounding whitespace is not a valid token
spelling.

Azure delivery writes each token to a digest-derived Key Vault secret name and changes the Core
reference only in the new Terraform revision. It never overwrites the versionless secret name used
by the active revision before the replacement plan succeeds. A failed renewal can therefore leave
an unused secret, but it cannot misbind or downgrade the running Core process.

## Token canonicality

A license has exactly one valid spelling. Base64 decoding in most standard libraries drops
characters outside the alphabet, so whitespace inserted into either segment would decode to the same
signed bytes and keep the signature valid - one license, unlimited distinct token strings. Segments
MUST match the unpadded base64url alphabet, and the decoded bytes MUST re-encode to the segment that
arrived. The decoded document must also reserialize to the exact canonical JSON bytes that arrived;
equivalent JSON with different whitespace, key order, list order, or timestamp spelling is rejected.

This matters for what gets built later rather than for what exists today. Revocation, reuse
detection, and audit correlation all key on the token; each would be built on an identifier that is
not unique. Leading or trailing whitespace is also a different spelling and is rejected rather than
trimmed before parsing.

## Resolution and degradation

Resolution fails toward safety. Every unhappy path degrades to the read-only subset of the catalog
rather than raising, so an operator with an expired license can still observe while unable to act.
This includes a verifier that cannot run at all: a corrupt packaged public key resolves to
`untrusted`, never to a crash, because that is precisely when a runtime has to stay up to be
diagnosed. The operator-facing reason stays generic and never echoes verifier exception details.

| Status | Cause | Availability |
|--------|-------|--------------|
| `issuer-workstation` | local source checkout proves possession of the integrity signing private key | full catalog; any configured token is ignored |
| `active` | signature verifies, inside the window, bindings match | listed capabilities that exist in the catalog, plus every read-only capability |
| `active` installation entitlement (target) | signature verifies and both installation bindings match; no window applies | the complete shipped catalog |
| `absent` | no token configured and no issuer-workstation proof | read-only in the shipped runtime |
| `untrusted` | malformed token, a non-canonical token, a signature the packaged key rejects, or a verifier that cannot run | read-only |
| `not-yet-valid` / `expired` | outside the validity window | read-only |
| `misbound` | distribution identity, image digest, or deployment binding does not match | read-only |

Every status that withholds the acting capability shows the
[Trial expiry watermark](#trial-expiry-watermark).

The crypto-free resolver keeps its explicit `require_license` input for isolated library and fork
composition. The shipped Core runtime always sets it. Development remains unrestricted only on a
verified issuer workstation; another checkout receives the same observation-only Trial posture as a
deployment with no token.

## Runtime execution ceiling

Availability is checked at the shared Thor execution port, which is used by normal control-loop
dispatch and human-approval resume. All PR-native, direct-API, and tool-call action paths require the
catalog capability `operations.typed-mutation`. The runtime resolves entitlement again immediately
before each port call. A process that crosses `not_after` therefore rejects the next acting request
without a restart, even if the token was active at startup.

A rejection writes a secret-free terminal audit record containing the status, license id when
available, expiration, required capability, and execution path. It never records the token, document,
signature, public-key bytes, private-key path, or verifier exception. Rejection cannot convert to
human approval or another executor path. If audit persistence fails, the delegate remains blocked
and the caller still receives a terminal denial marked `audit_persisted=false`; a secret-free
structured error provides the secondary operational signal instead of turning denial into an
unhandled execution-path exception.

This ceiling can only remove availability. A token that includes `operations.typed-mutation` still
needs every ordinary promotion, RBAC, risk, approval, safeguard, identity, and effect-verification
check before an effect. Replacing a token requires a Core restart so startup can bind the new secret;
expiration itself does not require one.

## Where the code lives

| Concern | Location |
|---------|----------|
| Token contract, validation, canonical bytes | `services/core-control-plane/src/fdai/core/licensing/token.py` (crypto-free) |
| Status, binding, current-time entitlement resolution | `services/core-control-plane/src/fdai/core/licensing/entitlement.py` |
| Runtime signature and local issuer-key verification | `services/core-control-plane/src/fdai/delivery/trust/ed25519.py`, verifying against the packaged `upstream-signing-key.pub` |
| Runtime Trial binding | `services/core-control-plane/src/fdai/runtime/licensing.py` |
| Durable Trial store and anchored activation writer | `services/core-control-plane/src/fdai/delivery/persistence/postgres_licensing_trial.py`, `services/core-control-plane/src/fdai/runtime/licensing_trial_activation.py` |
| Final shared execution ceiling | `services/core-control-plane/src/fdai/core/executor/licensing_gate.py` |
| Issuing and self-verification (release-only) | `scripts/deployment/release/issue-license.py`, using Ed25519 from the pinned cryptography dependency and exclusive mode-`0600` output creation |
| Offline verification for any operator | `fdaictl license inspect`, using the deployment CLI's independent Ed25519 verifier |
| Manifest-only integrity verification | `scripts/integrity/check-integrity.sh`, which rejects any other signed document shape in every mode |

The split matches the extension and skill trust seams: `core/` declares a `LicenseVerifier` Protocol
and never imports a crypto backend, a transport, or `fdai.delivery`
([project-structure.md](../architecture/project-structure.md#module-boundaries)).

Core and the deployment CLI each package a byte-identical copy of
`security/integrity/upstream-signing-key.pub`, and tests pin both copies to it. The runtime licensing
binding, the durable Trial store and its activation writer, and the `fdai/delivery/trust/` package,
including that copy, belong to the signed framework
surface.

## Verifying it in this repository

Licensing is testable without exposing the issuer private key. On the issuer workstation, issue a
30-day full-catalog token and inspect it:

```bash
uv run python scripts/deployment/release/issue-license.py \
  --license-id lic-0001 --distribution-id example-distribution \
  --all-capabilities \
  --output /tmp/license.token
uv run python -m fdai.deployment_cli license inspect \
  --token /tmp/license.token \
  --public-key security/integrity/upstream-signing-key.pub \
  --output json
```

`issue-license.py` re-verifies its own output against the supplied public key before printing, so a
rotated signing key fails at issue time rather than at the customer site. It reads only the fixed
`secrets/integrity-signing-key.pem`, as a current-UID mode-`0600` regular file, and reads both keys
through a nonblocking, no-follow, 65536-byte boundary. Its defaults are the packaged public key and
30-day validity; an explicit public key remains available for rotation verification. `license
inspect` reports status and non-secret metadata only; it never echoes the token, the document, or
the signature.

Automated coverage lives in `services/core-control-plane/tests/core/licensing/` for the contract and degradation table, and in
`tests/integration/scripts/test_issue_license.py` for a real issue-then-verify path including tampering, a wrong
signer, and a wrong binding.

## Honest limits

Signature verification is **tamper-evident, not tamper-proof**, exactly as recorded for the
framework-surface manifest. A customer who receives an image controls its runtime and can remove the
check; obfuscation only changes how long that takes.

The Trial and its watermark share that limit. Removing either requires changing signed
framework-surface code, which only verification against the upstream-signed manifest exposes. FDAI
does not claim to stop an operator who controls the source and runtime from running modified code.

The enforceable part is therefore the distribution channel, not the binary:

- record `license_id` in the audit trail so entitlement is attributable after the fact;
- tie updates, support, and each newly signed offline kit to a current license, which makes losing
  the next release the real consequence;
- prefer short validity windows with renewal, because a disconnected site has no revocation path and
  the host clock is outside the publisher's control.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/fork-and-sequencing/capability-licensing.md) |
| What a fork may edit and what it must inject | [downstream-fork-guide.md](downstream-fork-guide.md) |
| Capability bundles, extensions, and their trust checks | [project-structure.md](../architecture/project-structure.md#capability-bundles) |
| Secret handling and network boundaries | [security-and-identity.md](../architecture/security-and-identity.md) |
| Delivering an image and kit into a closed network | [disconnected-deployment.md](../deployment/disconnected-deployment.md) |
| How a deployment selects Trial or full entitlement | [source-deployment.md](../deployment/source-deployment.md) |
