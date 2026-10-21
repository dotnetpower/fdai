---
title: Hub-Managed Entitlement Continuity
---
# Hub-Managed Entitlement Continuity

This decision defines how a future Hub-managed installation receives entitlement without making
the Hub a licensing authority. It preserves the existing installation/deployment-bound entitlement
and original Trial anchor through upgrades, imports and recovery.

> **Status:** Direct/offline full-entitlement transport and local acceptance have source
> implementations. Hub API/Plan integration, rotation and installed qualification remain open.

## Design at a glance

Choose installation-local licensing verification and persistence, with transport-only Hub
mediation. An existing entitlement may be delivered through an installation-confidential envelope;
the Hub sees ciphertext and public lifecycle digests, not private signing keys or clear license
content. Direct installation/offline handoff remains possible under the same verifier.

A Release, Plan, channel subscription, configuration revision, Hub signature or enrollment does
not create a license. License eligibility never grants execution, approval, promotion or policy
authority, and it never exceeds the Release maximum or constitutional hard constraints.

## Existing authority and compatibility

[Source deployment](source-deployment.md#design-at-a-glance) owns its two existing outcomes:
one durable 30-day Trial without the integrity signing key, or an installation-bound full-catalog
entitlement when that key is usable. Its documents are domain-separated even where one key
protects both integrity and licensing. A present unusable key does not silently select Trial.

[Offline deployment](disconnected-deployment.md) retains its signed kit and independent
verification boundary. Neither existing installation path gains a Hub, a new signing-key input,
a published Release or CI result as a prerequisite.

[Runtime licensing](../../../services/core-control-plane/src/fdai/runtime/licensing.py) remains
the installation composition boundary.
[The durable Trial store](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_licensing_trial.py)
preserves the winning first activation record; a missing row is unactivated, not permission to
activate on read. Existing source recovery preserves the original installation anchor.

## Delivery decision

| Owner | Responsibility | Not permitted |
|-------|----------------|---------------|
| Existing licensing issuer/key holder | Issue the existing installation/deployment-bound licensing document through its approved path | A Hub or customer configuration signer cannot impersonate this issuer |
| Hub or Target Hub | Carry opaque installation-confidential bytes and exact digests; report bounded availability | Mint, renew, widen or reinterpret an entitlement |
| Installation Agent/handoff adapter | Verify exact recipient and transport purpose, then hand original bytes to the local licensing owner | Turn successful transport, decryption or a Plan signature into license acceptance |
| Installation licensing owner | Independently verify issuer, document purpose, binding, current state and applicable expiry; persist through existing ownership | Reset a Trial or substitute slot/source/image identity for installation/deployment identity |

The future carrier uses a purpose-distinct authenticated envelope. Installation encryption material
is independently provisioned for that role; no signing identity is converted into an encryption key.
Envelope decryption is confidentiality only. The unchanged inner issuer signature and local
licensing checks establish eligibility.

### Initial full-entitlement carrier contract

The first source increment is a direct/offline carrier and local licensing-owner handoff, not
a Hub API, Lifecycle Plan extension or deployed Hub-managed installation. It carries only an
existing `fdai.installation-entitlement.v1` token; expiring v1 licenses and Trial records are not
converted or transported by this increment.

| Boundary | Selected contract |
|---|---|
| Public envelope | `fdai.lifecycle.entitlement-carrier.v1` has an exact schema/purpose, installation and deployment binding digests, recipient fingerprint, ephemeral X25519 public key, nonce and ciphertext. Canonical JSON is bounded to 16 KiB and original token bytes to 8 KiB. |
| Confidentiality | Independently provisioned X25519 recipient material, HKDF-SHA256 and AES-GCM use a fixed entitlement-only domain and authenticated header. No signing key conversion or configuration-key lookup exists. Encryption is not evidence of issuer authority. |
| Issuer and handoff | The producer only seals bytes. The local importer independently verifies the unchanged inner document with the packaged licensing verifier and exact distribution/installation/deployment binding before acceptance. No command-line issuer-key override or Hub licensing authority is added. |
| Durable acceptance | Core alone owns a private PostgreSQL record and matching acceptance audit in one transaction. The exact token digest is idempotent; a different token for an already accepted binding is a conflict and cannot replace it. There is no timestamp-based winner, automatic rotation, clear or delete API. |
| Runtime | An explicit accepted-store source is optional and exclusive with the legacy environment token. Every acting resolution rereads the accepted record off the event loop and verifies its original issuer signature through the existing authority. Missing/corrupt storage is explicit; it never creates a Trial. Legacy omission preserves current source/offline behavior. |
| Visibility | Receipts expose digests and original acceptance time, never token/key bytes or license content. Operator continues to read only the existing entitlement notice, not the private token record. |

Critique rejects automatic replacement ordered by `issued_at`: that field is not an issuer
revision or a new validity window. A repeated original token returns the original acceptance
identity and receipt; changed ciphertext does not create a new entitlement. Distinct valid tokens
hold for a future separately governed rotation contract. The current Trial activation, expiry,
clock history and watermark rules remain unchanged. Source proof does not qualify a connected or
offline installation, a new key ceremony, old-binary compatibility, or Hub transport.

The original document and selected trust metadata are verified before atomic local acceptance.
Duplicate deliveries retain the same identity and result; older or conflicting state does not
replace a newer authoritative record. A missing carrier or private input is unavailable, not full
entitlement and not a newly started Trial.

### Local source commands

`fdaictl license seal-entitlement` takes private original-token and X25519 public-key files,
exact installation/deployment digests and a new private `--destination`. It emits only the carrier
digest and recipient fingerprint; `license_verified=false` makes its boundary explicit.
No signing-key input or new licensing document is created.

Run `python -m fdai.delivery.licensing_entitlement_import` in the local licensing-owner environment
with `--carrier`, `--recipient-key`, `--recipient-fingerprint`, `--installation-binding` and
`--deployment-binding`. It uses the existing Core database environment and packaged issuer trust,
not a CLI issuer-key override. `--inspect` with the two binding digests reads only the original
safe receipt. Storage errors leave the outcome unconfirmed: inspect before retrying.

Only `FDAI_ACCEPTED_INSTALLATION_ENTITLEMENT_SOURCE=postgres` opts Core into the accepted store;
both exact binding variables and its state database are required. An inline `FDAI_LICENSE_TOKEN`
cannot compete with that source. Startup logging performs no store read, and acting resolution
uses the existing worker-thread boundary. An absent row may use an existing valid Trial under
the unchanged resolver; corrupt/unavailable or rejected input cannot obtain a Trial fallback.

## Trial and recovery invariants

The entitlement and Trial bind installation/deployment identity, not Release version, source
commit, image digest, Plan sequence, slot or configuration revision. Preserve the existing path's
original Trial anchor and resulting expiry, including the source path's installation-creation
anchor. Keep activation and clock-safety records with the authoritative installation store,
outside replaceable slots.

| Event | Required result |
|-------|-----------------|
| Upgrade, restart or channel change | Reuse the original entitlement/Trial; do not start a window |
| Slot rollback or replayed import | Read current authoritative licensing state, not a slot-local older copy |
| Same-installation recovery with a lost record | Recover the verified original anchor and clock-safety state through the existing authorized recovery path; never use recovery time as creation time |
| Missing or conflicting original anchor | Hold acting eligibility; do not infer a fresh installation |
| New installation or deployment identity | Require that path's explicit current approval and independently valid binding; enrollment alone does not decide eligibility |
| Trial expiry | Keep existing expiry watermark and restrictions; observation, diagnosis, audit and export remain as the source owner defines |
| Expiry during a lifecycle phase | Follow the existing runtime's denial and permitted recovery semantics; never add a fallback entitlement |
| Clock rollback or missing monotonic history | Retain the existing clock-blocked/unknown outcome; a copied snapshot does not clear it |
| Wrong recipient, issuer, purpose or binding | Reject without replacing valid retained state |
| Revoked, unavailable or stale required trust | Hold the affected eligibility with a reason, rather than accepting an old cached assertion as current |

Offline acceptance verifies the same inner licensing document. Bundle freshness, recall and
licensing eligibility are separate decisions; a new bundle cannot renew a Trial. Offline inability
to learn a current change remains an explicit limitation, not a hidden network fallback.

## Critique and revision

| Rejected assumption | Selected boundary |
|---------------------|-------------------|
| A signed Release implies full entitlement | Verify the separate licensing purpose and installation/deployment binding |
| Enrollment starts a Trial | Only the existing authorized activation owner may create the original record |
| Hub renewal can extend the installation | The Hub is transport-only and cannot change the inner document or Trial anchor |
| Rollback can restore an earlier clock/licensing record | Retain current shared installation state and clock-safety history |
| Decryption proves an entitlement | Independently verify the inner issuer and eligibility after transport |
| Offline bundle import is a new installation | Preserve identity, original anchor, expiry and duplicate semantics |

## Remaining implementation and evidence

- [x] Implement the direct/offline purpose-distinct carrier and local licensing-owner handoff
  in #2352, without a Hub issuer, new token or Trial transition.
- [ ] Wire actual Hub opaque transport and a separately reviewed Lifecycle Plan handoff.
- [ ] Prove wrong-key/purpose/binding, replay, conflict, expiry, clock rollback and unavailable cases.
- [ ] Prove upgrades, slot rollback and same-installation recovery preserve the original anchor,
  watermark, clock restrictions and existing source/offline behavior.
- [ ] Retain independently observed connected and offline installation acceptance through the
  current licensing verifier, without repository-held private keys or fabricated Trial records.

No licensing token, Trial activation, signing key, deployment or authority transition was created
to publish this decision. These obligations remain separate from completing the design spike.

## Related docs

| To learn about | Read |
|----------------|------|
| Existing source semantics | [Source deployment](source-deployment.md) |
| Existing offline semantics | [Disconnected deployment](disconnected-deployment.md) |
| Slot failure and recovery boundaries | [Self-upgrade failure analysis](hub-managed-lifecycle-self-upgrade.md) |
| Normative Hub lifecycle | [Hub-Managed Lifecycle](hub-managed-lifecycle.md) |
| Decision delivery | [Implementation ledger](../../roadmap-implementation/deployment/hub-managed-lifecycle-entitlement.md) |
