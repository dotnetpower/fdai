# Lifecycle configuration key onboarding

Use this runbook to prepare customer ownership, key custody and the public verification binding
for lifecycle configuration packages. It separates those prerequisites from the implemented local
packager and the unimplemented operational key registration and Hub import paths.

> **Stop condition:** This runbook does not register, generate, rotate or export a key, and it
> provides no Hub import command. The [local CLI](../roadmap/deployment/lifecycle-configuration.md#local-packaging-and-verification-commands)
> signs and verifies explicit private files; it does not establish key trust or qualify a Release.
> Do not publish real configuration until operational key binding, qualified Release inputs and
> Hub import are implemented and independently verified.

## What this runbook covers

The customer configuration key authenticates a reviewed desired-configuration revision. It is
different from the vendor Release key and from the installation key that protects sealed
identifiers. None of these keys grants operational approval, promotion or executor authority.

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

These are operational acceptance requirements. Local package signing and verification implement
only the offline boundary; they do not establish installation trust or implement Hub import.

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
uncertain, hold new publication until reviewed rotation and readback are implemented.

## Next steps

| To learn about | Read |
|----------------|------|
| Value classes and package contract | [Lifecycle Configuration](../roadmap/deployment/lifecycle-configuration.md) |
| Implemented and remaining scope | [Configuration ledger](../roadmap-implementation/deployment/lifecycle-configuration.md) |
| Installation-side authority | [Hub-Managed Lifecycle](../roadmap/deployment/hub-managed-lifecycle.md) |
