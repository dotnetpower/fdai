# Lifecycle configuration key onboarding

Use this runbook to prepare customer ownership, key custody and the public verification binding
for lifecycle configuration packages. It separates those prerequisites from the implemented local
packager and authenticated public-key source APIs. Actual operational onboarding and atomic Hub
package import remain separate acceptance work.

> **Stop condition:** This runbook does not register, generate, rotate or export a key, and it
> provides no Hub import command. The [local CLI](../roadmap/deployment/lifecycle-configuration.md#local-packaging-and-verification-commands)
> signs and verifies explicit private files; it does not establish key trust or qualify a Release.
> The source APIs below have only synthetic local verification. Do not publish real configuration
> until actual key onboarding, qualified Release inputs and Hub import are independently verified.

## What this runbook covers

The customer configuration key authenticates a reviewed desired-configuration revision. It is
different from the vendor Release key, the enrolled Ed25519 installation identity and the X25519
installation key that protects sealed identifiers. None of these keys grants operational approval,
promotion or executor authority.

## 1. Prepare the private repository

Copy the [placeholder template](../../config/lifecycle-configuration-template/README.md) into a
customer-owned private repository. Keep the synthetic `release-schema.yaml` as an example only;
an actual package needs the schema of its independently verified target Release.

Review every value before replacing a placeholder:

| Value | Destination |
|-------|-------------|
| Region, sizing, version range and Entity overrides | Configuration layers |
| Tenant, subscription, resource names and endpoints | Private sealing input |
| Integration credential | Key Vault; the repository stores only its reference |
| Approval profile, admission policy or standing authority | Existing governed policy path, never configuration |

Keep upstream FDAI customer-agnostic. Do not attach populated files to public issues or logs.

## 2. Assign key custody

Name the accountable configuration owner and recovery approver through the customer's normal
governance process. Select provider-hosted custody or another reviewed signing boundary that
does not export private key material. Algorithm and registration details need the reviewed
package contract; this runbook does not invent a compatible signer.

Keep private material out of chat, command arguments, repository files, logs and screenshots.
Record only the public key reference, fingerprint, intended installation binding and review
identity in the customer's protected records. A public key copied from an untrusted package
cannot establish trust in that same package.

## 3. Review the verification binding

Before onboarding can complete, the implementation needs to demonstrate all of these checks:

- The exact installation independently trusts the customer configuration verification key.
- The signed revision binds its Git commit, predecessor digest and content digests.
- Unsigned, wrong-key, reordered and forked revisions fail before Plan computation.
- Sealed identifiers are encrypted to the correct installation key; a Hub keeps only ciphertext
  and digests, never their readable input.
- Secret values are rejected before signing; Key Vault references are not dereferenced by the Hub.
- Changing configuration cannot change policy, promotion state or execution authority.

These are operational acceptance requirements. Local package signing and verification alone do
not establish installation trust or implement Hub import.

### Source-only authenticated public-key workflow

The existing authenticated Hub now exposes these routes for an already enrolled installation.
They accept public metadata and proofs only, never private keys or credentials:

| Route below `/v1/installations/{installation_id}/configuration-keys` | Input or result |
|------------------------------------------------------------------|-----------------|
| `POST /request` | Canonical request bytes, installation identity proof and separate configuration-signer proof |
| `GET /requests/{request_digest}` | Exact public request and digest for independent review |
| `POST /approve` | Exact `request_digest`; the authenticated operator differs from the signed requester |
| `POST /revoke` | Exact current `request_digest`; removes configuration trust without deleting history |
| `GET` | Current version, approved digest, approver and revocation state |

The [owner design](../roadmap/deployment/lifecycle-configuration.md#approved-configuration-keys-design-and-critique)
defines canonical fields, separate algorithms, five-minute proof freshness, ten-minute approval
expiry, bounded binding expiry and predecessor/version comparison. Actor fields and package keys
are not approval. Unauthenticated loopback calls cannot register or approve this trust. The
explicit Lifecycle Hub revision 1-to-2 migration is additive; serving does not migrate data.

The real planning store resolves persisted approved bindings. A server-owned configuration
candidate can reach the existing remote recompute API through its explicit composition seam;
there is no customer-package upload/import command or durable accepted-chain head. Rotation
retains old public metadata and holds old pending Plans. Historical packages are not reinterpreted
with the replacement signer; cross-key accepted-chain import remains separate work.

## 4. Check the placeholder structure offline

From the FDAI checkout:

```bash
uv run --no-sync pytest -q --no-cov \
  tests/integration/test_lifecycle_configuration_template.py
```

The focused test uses the implemented pure validators and synthetic values. It creates no key,
signature, package, upload, Azure call or operational receipt. Preserve the test revision and
result separately from any later connected acceptance.

## 5. Plan recovery before publication

Document who can approve a key rotation and how the installation will authenticate the new
verification key through an independent trust channel. Preserve predecessor history; replacing
a key does not authorize a fork or a history reset. If the private key is lost or its custody is
uncertain, hold new publication until reviewed operational rotation and independent readback
succeed. The source-only API and synthetic tests do not perform that ceremony.

For an enrolled development installation whose identity private key is unavailable, don't replace
the Hub row or Agent files manually. Use the full-authority development recovery only after the
Lifecycle Hub deployment fixes the exact installation, scope, Owner object id, previous key id,
replacement public key, reason, and authorization interval of at most 14 days in
`operator_auth.development_recovery`.

1. Keep the selected replacement private key in the approved private key directory. Derive only
   its public key for deployment input.
2. Build canonical `fdai.development-identity-recovery.v1` bytes and sign them with that exact
   replacement key. The request confirmation names the installation, previous key id, and
   replacement key id.
3. Submit the signed request to
   `POST /v1/installations/{installation_id}/configuration-keys/recover-identity` as the exact
   configured Owner. A successful exact retry returns the same digest.
4. Read back the new installation key id and the append-only recovery audit before requesting a
   configuration signer binding.
5. The same Owner can approve only the first binding when the protected authorization explicitly
   permits it. Later rotations and every non-development installation still need a different
   operator.
6. Remove the recovery authorization after the first binding and verify a zero-change Hub plan.

Recovery stops when a Plan is open, configuration trust or a pending key request already exists,
the proof is older than five minutes, or any fixed input differs. It never repurposes the integrity
signing key, rewrites history, or carries private key bytes to the Hub.

## Next steps

| To learn about | Read |
|----------------|------|
| Value classes and package contract | [Lifecycle Configuration](../roadmap/deployment/lifecycle-configuration.md) |
| Implemented and remaining scope | [Configuration ledger](../roadmap-implementation/deployment/lifecycle-configuration.md) |
| Installation-side authority | [Hub-Managed Lifecycle](../roadmap/deployment/hub-managed-lifecycle.md) |
