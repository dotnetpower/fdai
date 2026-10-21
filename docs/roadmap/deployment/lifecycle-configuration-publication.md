---
title: Local Configuration Publication
---
# Local Configuration Publication

This document defines durable local publication of an explicitly selected configuration
revision. It fills the persistence seam between the existing package builder and a future
protected-merge publisher, without treating a local artifact as reviewed or accepted.

> **Scope:** A publication venue is one existing current-operator-owned mode-0700 directory.
> It is not global source registration, Git review, Hub acceptance or execution authority.
> [Lifecycle Configuration](lifecycle-configuration.md) owns the package and trust contracts.

## Design at a glance

Serialize one venue, independently validate its complete retained chain, persist the original
ciphertext/signature and receipt, then create and read back its private artifact copy. A retry
returns the original bytes and receipt, not a new encryption or signing attempt.

## Inputs and compatibility

Use the existing single-Entity and installation-wide v1/v2 input contracts, independent
Ed25519 verification key, X25519 recipient and Release/schema input. Existing `build` and
`verify` behavior and `fdai.lifecycle-configuration-file.v1` bytes remain unchanged.

The new publication path uses an explicit 40-character lowercase hexadecimal revision id.
That shape does not prove Git existence or review. The caller selects the venue and first
publication or expected publication head. This local chain is not an assertion that the Hub
has accepted any package. No key is discovered, converted, issued or registered.

## Durable state and privacy

The private SQLite journal retains original ciphertext/signature bytes, package/revision
identity, sequence and stable receipt metadata. It stores no extra plaintext input, private key
or secret. Artifact copies are mode-0600 files in the same private venue.

Support at most 256 packages and 16 MiB of retained artifact bytes. Reject overflow rather
than truncate. Journal schema version 1 is explicit; an unknown, corrupted or incomplete
retained schema holds for review instead of being recreated as an empty chain.

One local directory lock serializes cooperating writers. It does not replace a target,
execution or cross-venue lock. An independently selected authoritative venue and tested
backup/restore remain prerequisites of a future automated publisher.

## Commit, retry and recovery

| Stage | Result | Uncertain outcome |
|-------|--------|-------------------|
| Validate retained state and requested input | Existing builder/reader verifies complete history and exact retry inputs | Preserve history and refuse |
| Commit original package and receipt | One durable publication identity | Inspect retained evidence before retrying |
| Materialize private artifact | Exclusive new file; an existing copy must match exactly | Never overwrite a conflicting copy |
| Independently read back | Exact bytes and independent reader verification | Publication is not confirmed |

If a process stops after journal commit but before artifact creation, retry materializes the
same retained bytes without re-signing. The original receipt time and identity do not change.
A same-revision input conflict, key/context mismatch or forked history is explicit.
For a historical retry, independently verify the current complete chain before comparing inputs
against the retained prefix. Returning an earlier receipt never rewinds the publication head.

Read-only inspection verifies the retained chain with independent public inputs and reports
the original receipt plus artifact presence. It needs no signing key and creates no artifact.
There is no clear, delete, reset, rotation or destructive recovery command.
Pending SQLite transaction sidecars and unsupported storage modes hold for review. Inspection
does not perform SQLite recovery or create journal/shared-memory files.

## Local commands

Select an existing empty private venue and independent input/key files. For example:

```bash
fdaictl configuration publish --state-dir /absolute/private/publications \
  --input /absolute/private/source.json --release-input /absolute/private/release.json \
  --configuration-key /absolute/private/configuration.pem \
  --installation-key /absolute/private/installation.pem \
  --signing-key /absolute/private/signing.pem --initial-publication --output json
```

For a subsequent new revision, replace `--initial-publication` with
`--expected-publication-head <retained-package-digest>`. Inspect without signing material:

```bash
fdaictl configuration inspect-publication --state-dir /absolute/private/publications \
  --revision-id aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --release-input /absolute/private/release.json \
  --configuration-key /absolute/private/configuration.pem \
  --installation-key /absolute/private/installation.pem --output json
```

The result separates `verified` retained evidence from `publication_confirmed` artifact readback.
A missing copy reports `artifact_state: missing` and `publication_confirmed: false` without repair.
All Git/global-publisher assertions remain unverified, and Hub/activation/authority flags stay false.

## Design critique and revision

- A filesystem existence check alone permits concurrent encryption and divergent retries.
  Hold the existing private-directory lock across validation, commit and artifact readback.
- Writing the file before recording its publication loses the original decision after a crash.
  Commit original bytes first, then recover only those bytes.
- A local journal or revision-shaped string cannot prove protected Git review or global
  publisher identity. Keep those facts explicitly unverified; don't grant import or activation.
- A corrupted or missing state file is not permission to start over. Require explicit initial
  publication only in an empty venue and reject orphan/conflicting retained artifacts.
- A successful write is not acceptance or an operational effect. Report local publication
  only after readback, and use an explicit not-confirmed outcome after ambiguous failure.

## Related docs

| To learn about | Read |
|----------------|------|
| Package, history, sealing and independent trust | [Lifecycle Configuration](lifecycle-configuration.md) |
| Hub import and installation boundaries | [Hub-Managed Lifecycle](hub-managed-lifecycle.md) |
| Delivery evidence and remaining work | [Implementation ledger](../../roadmap-implementation/deployment/lifecycle-configuration-publication.md) |
