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

The connected source deployment will initialize one 30-day Trial at first activation through an
authenticated deployment writer. Its installation and deployment bindings are independent from
the source revision and image digest, so an ordinary upgrade or restart cannot renew the Trial.
The activation time never changes. Every durable observation advances a revision and the
last-observed UTC time; a clock regression creates a persistent blocked state, not another Trial.
The first observation at or after expiry blocks new acting requests without stopping observation,
diagnosis, audit, export, or safety-required in-flight completion and recovery.

The initial implementation adds only the inert record and deterministic transition contract.
Runtime availability remains on the existing signed-token path until atomic persistent storage,
authenticated initialization, cross-process readback, and all-path execution gating are connected
and tested. Missing or inconsistent retained records never authorize reinitialization. Malformed
or expired signed credentials must not create a fresh Trial fallback.

A future versioned entitlement can remove the Trial restriction; the current signed-token
30-day ceiling remains unchanged until that contract is implemented. A signed deployment kit
authenticates artifacts, not usage rights. It removes Trial only when it carries a separately
valid entitlement. Publisher private keys never enter the deployment. A source owner who also
controls all persistent state can remove these checks; this offline mechanism does not claim
tamper-proof enforcement or global reinstall detection.

## Issuer workstation exception

**Initial design.** Treat the presence of any private-key file under `secrets/` as proof that the
runtime is on the issuer workstation, then skip licensing.

**Critique.** A filename is not a cryptographic identity. An empty file, an unrelated key, a
symlink, or a mounted key path would satisfy a presence check. Reusing
`secrets/integrity-signing-key.pem` would also collapse framework-integrity and license compromise
domains and make the runtime read a key it does not need.

**Revised design.** A source checkout may enter `issuer-workstation` status only when every check
below passes:

- the execution venue is `local` and the asset root has a Git checkout marker;
- the fixed `secrets/license-signing-key.pem` path is a current-UID, mode-`0600` regular file read
  through a bounded, nonblocking, no-follow descriptor;
- the file contains an Ed25519 private key whose derived public bytes exactly match the tracked
  license public key packaged with the Core distribution; and
- the dedicated license key is separate from `secrets/integrity-signing-key.pem`.

The runtime does not open the private-key path in a deployed venue. The Docker build context excludes
the complete `secrets/` tree. A verified issuer workstation ignores any configured license token and
keeps the full catalog available, while all promotion, RBAC, risk, approval, rollback, audit, and
effect-verification gates remain unchanged. Missing, malformed, incorrectly permissioned, or
mismatched private-key material grants no exception and does not stop observation.

This proves possession of the dedicated key, not attachment to immutable physical hardware. Copying
the key copies issuer status. A later hardware-backed key design can strengthen that custody boundary
without changing the signed token contract.

## The token

The token is `base64url(canonical-document) "." base64url(signature)` - a single ASCII string that
fits an environment variable, a Container Apps secret, or a Kubernetes Secret mount. The signature
covers the exact canonical document bytes, so field order cannot be reinterpreted, and
`schema_version` inside the document keeps the payload domain-separated from every other FDAI
signature.

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
| `issuer-workstation` | local source checkout proves possession of the dedicated matching private key | full catalog; any configured token is ignored |
| `active` | signature verifies, inside the window, bindings match | listed capabilities that exist in the catalog, plus every read-only capability |
| `absent` | no token configured and no issuer-workstation proof | read-only in the shipped runtime |
| `untrusted` | malformed token, a non-canonical token, a signature the packaged key rejects, or a verifier that cannot run | read-only |
| `not-yet-valid` / `expired` | outside the validity window | read-only |
| `misbound` | distribution identity, image digest, or deployment binding does not match | read-only |

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
| Runtime signature and local issuer-key verification | `services/core-control-plane/src/fdai/delivery/trust/ed25519.py` |
| Runtime Trial binding | `services/core-control-plane/src/fdai/runtime/licensing.py` |
| Final shared execution ceiling | `services/core-control-plane/src/fdai/core/executor/licensing_gate.py` |
| Issuing and self-verification (release-only) | `scripts/deployment/release/issue-license.py`, using Ed25519 from the pinned cryptography dependency and exclusive mode-`0600` output creation |
| Offline verification for any operator | `fdaictl license inspect`, using the deployment CLI's independent Ed25519 verifier |

The split matches the extension and skill trust seams: `core/` declares a `LicenseVerifier` Protocol
and never imports a crypto backend, a transport, or `fdai.delivery`
([project-structure.md](../architecture/project-structure.md#module-boundaries)).

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
  --public-key services/core-control-plane/src/fdai/delivery/trust/license-signing-key.pub \
  --output json
```

`issue-license.py` re-verifies its own output against the supplied public key before printing, so a
rotated signing key fails at issue time rather than at the customer site. It accepts the private key
only as a current-UID mode-`0600` regular file and reads both keys through a nonblocking, no-follow,
65536-byte boundary. Its defaults are the fixed issuer key, packaged public key, and 30-day validity;
an explicit public key remains available for rotation verification. `license inspect` reports status
and non-secret metadata only; it never echoes the token, the document, or the signature.

Automated coverage lives in `services/core-control-plane/tests/core/licensing/` for the contract and degradation table, and in
`tests/integration/scripts/test_issue_license.py` for a real issue-then-verify path including tampering, a wrong
signer, and a wrong binding.

## Honest limits

Signature verification is **tamper-evident, not tamper-proof**, exactly as recorded for the
framework-surface manifest. A customer who receives an image controls its runtime and can remove the
check; obfuscation only changes how long that takes.

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
