---
title: Operate Cloud Resource Knowledge
---
# Operate cloud resource knowledge

Use this procedure to collect reviewed public cloud documentation, inspect signed data-only
packages, and submit new knowledge generations through FDAI's existing document approval pipeline.
Collection, package verification, and import are separate from approval and searchable activation.

> **Scope:** The software supports bounded Azure source collections and complete JSON packages.
> Establish source rights, production signing trust, internal reviewers, and deployment configuration
> before enabling collection. Local tests do not establish those approvals or a production rollout.
>
> **Structured implementation:** Original-free v2 remains the default. The v3 opt-in is implemented;
> source qualification, independent answer review and production rollout remain separate.

## Requester application: target and current operation

The [target workflow](../roadmap/interfaces/cloud-resource-knowledge-lifecycle.md#requester-initiated-application-target)
lets an authorized requester apply eligible reference content under previously approved policy,
without choosing another approver for every document. The uploader need not be identified during
preparation; the real intake request supplies the authenticated identity. Content review can start
before that request exists and does not itself grant runtime approval authority.

This policy-backed application path is **not implemented**. The procedures below describe the
current manual lane, not a permanent requirement to arrange another person for every future update.
There is no supported setting that turns `Reader`, a successful import, or a package signature into
activation authority. Do not change roles, forge approval fields or disable Var to simulate the target.
After implementation and independent promotion, eligible requests should proceed without a manual
wait while preserving scanning, policy rechecks and independently verified index completion.

## Prerequisites

- **Services:** Run the existing Core, Operator, ingestion API, and document worker with their own
  database roles and the normal document event/approval bindings. No new service is required.
- **Schema:** Apply the ingestion `cloud_knowledge_20260914` and worker
  `cloud_knowledge_lexical_20260914` migrations through the normal deployment workflow.
- **Sources:** Independently review the exact source URLs, collection, resource applicability,
  license, storage/transfer rights, refresh interval, and expiry in `SourceRegistryRevision`.
  `azure_network_sources()` provides disabled APIM, VNet, NSG, and Private DNS starter templates.
- **Trust:** Establish independently approved Ed25519 public keys and current revocation evidence
  in `KnowledgeTrustPolicy`. Never obtain initial trust from the package being inspected.
- **Current manual-lane reviewers:** Use separate requester and approver identities. The existing
  Approvals surface carries Var decisions; a package uploader cannot approve their own content.
- **Scanner:** Supply the normal replica-local ClamAV service and current signature data.
  Cloud-reference inspection and activation require a signature database less than seven days old.

## Configure each participating service

These values are deployment configuration, not source-code examples containing customer values.
Mount independently reviewed policy files read-only and protect their parent directories.

| Setting | Services | Meaning |
|---------|----------|---------|
| `FDAI_CLOUD_KNOWLEDGE_REGISTRY_PATH` | ingestion API, worker, Core | Path to the same reviewed source registry revision |
| `FDAI_CLOUD_KNOWLEDGE_TRUST_PATH` | ingestion API, worker, Core | Independently managed signing trust and revocation evidence |
| `FDAI_CLOUD_KNOWLEDGE_FORMAT` | ingestion API | Default `v2`; explicit `v3` selects the structured format, not trust, approval, or activation |
| `FDAI_CLOUD_KNOWLEDGE_NORMALIZER_VERSION` | ingestion API | Default `2.0.0`; explicit `2.1.0` requires `v3` and compatible reader `3.1.0`; unknown/incompatible values fail startup |
| `FDAI_DOCUMENT_COLLECTIONS` | ingestion API | Includes every registered knowledge collection |
| `FDAI_DOCUMENT_RETRIEVAL_MODE` | ingestion API, worker | `lexical` avoids embedding construction and startup/query probes; `hybrid` preserves the existing default |
| Existing `FDAI_RCA_DOCUMENT_*` settings | Core | Bind the authorized governed document collection/read store to semantic conversations |

Missing both knowledge-policy paths reports the capability as unavailable. Supplying only one or an
invalid policy fails configuration. A changed source registry requires reloading its binding; trust
and read/activation policy are rechecked rather than accepted from client metadata. None of these settings
grants resource execution authority or changes the document scanner, access, or approval boundary.

Select `FDAI_CLOUD_KNOWLEDGE_FORMAT=v3` only for a bounded candidate after confirming compatible
collector, API/CLI, worker, and Core readers in the selected build. This does not migrate retained
v1/v2 records, activate a generation, or authorize live source/model calls. The
[structured design](../roadmap/interfaces/cloud-resource-knowledge-structured-rag.md) owns body blocks,
excerpt derivation, and separate retrieval-query qualification.

In a disconnected environment, keep every source in `offline` mode and set document retrieval to
`lexical`. Enforce no public DNS/HTTP egress at the network boundary as well. The knowledge codec,
indexing, and retrieval do not download a model or substitute fabricated vectors. Other product
capabilities retain their own connectivity requirements.

## Connected collection and review

1. Open **Knowledge > Overview > Cloud reference knowledge** and inspect the source policy and
   recorded state. Sources start disabled and require explicit approved storage rights.
2. An Owner can select **Check due sources**. The daily/startup sweep uses the same operation;
   it checks only enabled online sources whose policy is due, not every document on every tick.
3. Review each source's collection date, last successful check, latest attempt, gaps, and pending
   changes. A failure does not refresh source age. HTTP 429/503 stops the affected sweep.
4. Expand a collection and download its **unsigned review manifest**, or submit the complete
   collected revision for review. A partial failed collection cannot silently shrink its manifest.
5. In the current manual lane, follow inspection, independent human approval, and indexing.
   **Ingestion requested** means received, not active. The existing document pipeline owns progress.
  Pending index verification is unavailable. A separate read-only database observation must match
  the sealed source and complete chunk set before the fenced visibility transition reports success.
6. Reload recorded status. Confirm the intended active version and inspect its source citations.
   Runtime readiness and application/database success are not live Azure resource observations.

An unchanged source check updates the immutable check history and current same-body read projection
without re-embedding or replacing the active document. New body content remains a separate candidate.
The operational defaults are seven-day checks and a thirty-day unverified ceiling; reference
profiles can use thirty-day checks and a ninety-day ceiling after review.

## Prepare retained sources without network access

Use the installed `fdai_ingestion_api_service.cloud_knowledge.review` module to assess existing
collector files before a new release proposal. It performs no fetch, signing, approval, index write
or model call. The operating system must enforce any required egress isolation; the command does
not change the host network or claim production isolation on its own.

Prepare a UTF-8 JSON input with schema `fdai.cloud-knowledge-review.v1` and a `sources` array. Each
entry contains exact retained `CloudSourceEvidence` as `evidence`, its `title`, and `original_path`
and `normalized_path` relative to the selected source root. Preserve the original observations;
do not insert current timestamps or invented rights. Paths are bounded canonical POSIX names and
cannot traverse parents or symbolic/hard links. The plan references originals but never embeds them.

```bash
python -m fdai_ingestion_api_service.cloud_knowledge.review \
  --input /private/review-input.json --source-root /private/retained \
  --output /private/new-review --normalizer-version 2.1.0 \
  --per-source-seconds 30 --total-seconds 900
```

The paths are placeholders. Input and output parents must already exist; the output directory must
not exist. The command creates private files without overwriting prior evidence. It retains one
original-free structured candidate per successfully normalized source, including candidates with
explicit structural or excerpt-size holds. The canonical `report.json` binds the exact input hash,
candidate hashes, processing identities, original dates, byte accounting and complete source scope.
Failed inputs and expired budgets remain visible as held or unprocessed rows with unknown metrics.

| Boundary | Maximum |
|---|---|
| Input plan / source count | 2 MiB / 256 |
| Each original or normalized file / cumulative source bytes | 8 MiB / 64 MiB |
| Each candidate / cumulative candidate bytes | 16 MiB / 64 MiB |
| Child wire output / address space / CPU | 32 MiB / 768 MiB / 30 seconds |
| Per-source processing / total processing | 30 seconds / 900 seconds |

The child bounds normalization and complete excerpt measurement together. Progress reports expose
counts, not source text. A deadline never publishes a late candidate as successful; output I/O
failure is terminal and partial files are retained for diagnosis. Use local regular storage, not a
network-mounted path; processing deadlines are not a hard deadline for a blocked filesystem call.

Exit `0` means all declared sources are structurally processable, `1` means the complete report
contains holds/unprocessed sources, and `2` means invalid top-level input or output failure. Even
exit `0` leaves rights, independent review, production qualification and execution authority false.
Candidates and this report are not directly importable release manifests. Preserve the declared
scope for independent review and use the existing governed producer/signing path afterward.

## Prepare a signed offline package

The default v2 review manifest contains exact normalized UTF-8 text, per-source original and
normalized hashes, collection/check times, applicability, license reference, and complete collection
identity. The v3 format adds body blocks and sealed excerpt digests, not source originals.
Original HTML/Markdown is retained in the collector checkpoint and is not included in new
exports, packages, collected submissions, or rollback candidates. The 16 MiB hard ceiling remains;
ZIP/TAR, scripts, plugins, model weights, and database dumps are not accepted.
Split large source inventories into separately reviewed bounded collections, not an unchecked archive.

Default packages use `fdai.cloud-knowledge-package.v2`, manifest `fdai.cloud-knowledge.v2`, and
reader `2.0.0`. The opt-in v3 uses `fdai.cloud-knowledge-package.v3`, `fdai.cloud-knowledge.v3`, and
reader `3.0.0` for normalizer `2.0.0`, or reader `3.1.0` when any document uses `2.1.0`.
Older readers cannot consume newer representations. Upgrade the API/CLI and worker together and confirm
the full reader path before delivery. Retained v1/v2 bytes and signatures stay unchanged and remain
verifiable/importable under current admission gates. Never strip fields or relabel a signed package;
create a new review manifest and signature. Eligible v1/v2 rollback creates a higher-sequence v2
candidate; v3 rollback preserves its structure. Both pin the old manifest digest and preserve source
evidence and admission expiry.

The receiver verifies the included text's SHA-256 and signature. The original SHA-256 is signed
producer provenance, not a claim that the receiver rehashed an absent body. Verification makes no
network request to retrieve it. Removing originals does not remove text storage/transfer conditions,
attribution and modification notices, internal inspection, or independent approval. It also does not
qualify unresolved media, ambiguous tables or source-dependent context in [Issue #995](https://github.com/dotnetpower/fdai/issues/995).

An independently approved signing process signs the exact canonical manifest bytes prefixed with
the ASCII purpose `fdai.cloud-knowledge.release.v1` and one zero byte. It retains the private key.
This purpose is independent of the manifest's signed schema version. The signature is a raw
64-byte Ed25519 value. Changing any manifest byte requires a new signature.

The installed ingestion distribution includes an offline command module. Its `assemble` operation
accepts an exact canonical v2 manifest, or v3 in a compatible build, with a detached signature, key
identifier, registry, trust policy, and new output path. Original-body fields, v1 assembly, and
noncanonical input are rejected.
It verifies the result before writing it and refuses to overwrite an existing output. It never
reads or creates a private key. `inspect` verifies a complete package without importing it.

```bash
python -m fdai_ingestion_api_service.cloud_knowledge assemble \
  --input /private/review.json --signature /private/review.sig \
  --key-id approved-knowledge-key \
  --registry /approved/source-registry.json --trust /approved/knowledge-trust.json \
  --output /private/knowledge-package.json

python -m fdai_ingestion_api_service.cloud_knowledge inspect \
  --input /private/knowledge-package.json \
  --registry /approved/source-registry.json --trust /approved/knowledge-trust.json
```

Paths and the key identifier above are placeholders. Carry the verified package, source/license
inventory, change summary, and the organization's transfer-review record through approved media.
Do not carry keys, credentials, deployment configuration, or an approval override in the package.

## Inspect and import inside the restricted network

1. Open the knowledge panel and select the signed JSON package. Use **Inspect selected package**.
2. Check source dates and the manifest digest. **Verified candidate** proves package verification
   only. The preview arrival time is not an import receipt.
3. Confirm submission of the exact inspected bytes and select **Import inspected package for
   review**. The server verifies the bytes and current policy again and reserves the release sequence.
4. In the current manual lane, complete internal malware inspection and independent review through
  the document pipeline. Stale scanner data, expired trust/admission, mismatched policy, and
  self-approval block it.
5. Reload status and verify the intended document generation. Reference citations open stored
   document sections; an external source URL is provenance, not an automatic network request.

Identical requester/package replay reuses its recorded upload. A reused sequence with different
bytes, a lower sequence, or a different requester cannot overwrite that record. A lost HTTP response
does not prove cancellation; reload status before another request.

## Recovery and date interpretation

- **Old package:** Import preserves original source dates. A current signature or recent import
  cannot make an old document fresh. Historical explanation and current RCA eligibility differ.
- **Pending candidate:** A failed build leaves the prior generation unchanged. During the final
  swap, the new generation stays unavailable until independent readback passes. A failed readback
  contains it as unavailable with a terminal audit; it does not silently restore a prior version.
  Expected-version conflicts roll back the transition, and the durable effect journal resumes after a crash.
- **Rollback:** An Owner can submit a retained inactive version for rollback review. The new request
  has a higher sequence, preserves source dates and expiry, and needs independent approval. It cannot
  resurrect withdrawn or revoked content. Automatic containment does not authorize this restoration.
- **Expired trust:** Refresh independent trust/revocation evidence through the approved process.
  Do not alter dates, disable verification, import a package-supplied key, or bypass the clock check.
- **Five consecutive source failures:** The collector holds further attempts. Review the cause and
  approved source policy before issuing a new registry revision; do not erase audit/check history.
- **Full-text rights absent:** Keep the source reference-only. Do not export or import its full text.
- **Oversized section:** Legacy v1/v2 requires a complete heading-bounded section plus provenance
  within 8 KiB. The v3 path uses bounded structural excerpts with required context;
  an unsupported or oversized atomic unit holds the complete generation rather than dropping content.
- **Current guidance:** Exact typed resource conditions and fresh source evidence are required for
  an as-of operational explanation. A live-current request returns a new-observation requirement;
  answering does not trigger a source fetch, and import never resets the check date.

## Verification and evidence

Before production rollout, retain a real complete source collection and an egress-denied internal
package-to-answer drill with your actual signing root, security reviewers, scanner, service roles,
and policies. Include tamper, replay, source expiry, unavailable trust, duplicate worker, and rollback
cases. Repository tests use synthetic documents and test-only signing keys; they are not this receipt.
Local retained-source processing in an OS network namespace proves only that bounded preparation
ran with the recorded network restrictions. It does not prove internal import, reviewer identity,
stored retrieval, bilingual answer quality, signing trust or deployed network policy.

## Related docs

| To learn about | Read |
|----------------|------|
| Time, admission, and authority contracts | [Knowledge lifecycle design](../roadmap/interfaces/cloud-resource-knowledge-lifecycle.md) |
| Current software and operational gaps | [Implementation ledger](../roadmap-implementation/interfaces/cloud-resource-knowledge-lifecycle.md) |
| Structured format and retrieval-query boundaries | [Structured retrieval design](../roadmap/interfaces/cloud-resource-knowledge-structured-rag.md) |
| Structured implementation and qualification gaps | [Structured RAG ledger](../roadmap-implementation/interfaces/cloud-resource-knowledge-structured-rag.md) |
| Independent trust establishment | [Offline trust ceremony](offline-trust-ceremony.md) |
| Existing approval and indexing owners | [Document ingestion agent ownership](../roadmap/interfaces/document-ingestion-agent-ownership.md) |
