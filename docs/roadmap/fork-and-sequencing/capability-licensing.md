---
title: Capability Licensing
---
# Capability Licensing

A downstream distribution often reaches its customer as an image, not as source: the fork is built,
the image is handed over, and it runs inside a network the publisher cannot reach. This document
defines how such a distribution activates entitlement without shipping a secret, without a network
call, and without ever becoming a path to higher autonomy.

> **Scope:** The mechanism is upstream and identical for every distribution. The public key and the
> token are deployment configuration. This document does not define commercial terms, pricing, or a
> revocation service.

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

`tenant_binding` is never a tenant identifier. Binding by digest keeps the repository, the image, and
every log line free of customer values
([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).

## The rule that makes this safe

**A license moves the `available` axis only.** It can never promote a capability out of shadow,
widen a role, relax a risk decision, or grant approval authority. Those stay with the promotion
registry, RBAC, and the risk gate
([coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)).

The consequence is worth stating plainly: the worst outcome of a forged or stolen token is that an
operator sees a capability listed. It is never that a high-risk action executes. A licensing check
that could raise autonomy would itself be a backdoor.

Entitlement is also an intersection with the shipped catalog, so a token cannot invent a capability
the distribution does not implement.

## Resolution and degradation

Resolution fails toward safety. Every unhappy path degrades to the read-only subset of the catalog
rather than raising, so an operator with an expired license can still observe while unable to act.

| Status | Cause | Availability |
|--------|-------|--------------|
| `active` | signature verifies, inside the window, bindings match | listed capabilities that exist in the catalog |
| `absent` | no token configured | full catalog upstream; read-only when the distribution sets `require_license` |
| `untrusted` | malformed token, or a signature the packaged key rejects | read-only |
| `not-yet-valid` / `expired` | outside the validity window | read-only |
| `misbound` | image digest or deployment binding does not match | read-only |

This repository ships unlicensed, so `absent` keeps the full catalog and development is never gated.
A distribution that wants fail-closed behavior sets `require_license` at its composition root.

## Where the code lives

| Concern | Location |
|---------|----------|
| Token contract, validation, canonical bytes | `src/fdai/core/licensing/token.py` (crypto-free) |
| Status, binding, and entitlement resolution | `src/fdai/core/licensing/entitlement.py` |
| Signature verification | `Ed25519LicenseVerifier` in `src/fdai/delivery/trust/ed25519.py` |
| Issuing (release-only) | `scripts/deployment/release/issue-license.py` |
| Offline verification for any operator | `fdaictl license inspect` |

The split matches the extension and skill trust seams: `core/` declares a `LicenseVerifier` Protocol
and never imports a crypto backend, a transport, or `fdai.delivery`
([project-structure.md](../architecture/project-structure.md#module-boundaries)).

## Verifying it in this repository

Licensing is testable upstream even though upstream ships no license. Generate a key, issue a token,
then inspect it:

```bash
openssl genpkey -algorithm ed25519 -out /tmp/license-key.pem
openssl pkey -in /tmp/license-key.pem -pubout -out /tmp/license-key.pub
PYTHONPATH=src python3 scripts/deployment/release/issue-license.py \
  --private-key /tmp/license-key.pem --public-key /tmp/license-key.pub \
  --license-id lic-0001 --distribution-id example-distribution \
  --capability cost.metering --capability incident.restart \
  --output /tmp/license.token
PYTHONPATH=src python3 -m fdai.deployment_cli license inspect \
  --token /tmp/license.token --public-key /tmp/license-key.pub --output json
```

`issue-license.py` re-verifies its own output against the supplied public key before printing, so a
rotated signing key fails at issue time rather than at the customer site. `license inspect` reports
status and non-secret metadata only; it never echoes the token, the document, or the signature.

Automated coverage lives in `tests/core/licensing/` for the contract and degradation table, and in
`tests/scripts/test_issue_license.py` for a real issue-then-verify path including tampering, a wrong
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
| What a fork may edit and what it must inject | [downstream-fork-guide.md](downstream-fork-guide.md) |
| Capability bundles, extensions, and their trust checks | [project-structure.md](../architecture/project-structure.md#capability-bundles) |
| Secret handling and network boundaries | [security-and-identity.md](../architecture/security-and-identity.md) |
| Delivering an image and kit into a closed network | [disconnected-deployment.md](../deployment/disconnected-deployment.md) |
