---
title: Cloud Resource Knowledge Lifecycle
---
# Cloud Resource Knowledge Lifecycle

This design governs collection, refresh, delivery, admission, and citation of official cloud
resource documentation. You can use the same evidence contract for connected collection and
security-reviewed offline document packages without presenting an old snapshot as current guidance.

> **Implementation boundary:** Contracts, bounded collection, signed package intake, governed
> document activation, and dated lexical retrieval have local implementation evidence. Production
> trust establishment and live collection/air-gap rollout remain separate prerequisites. Azure is
> the first collection target; other cloud service providers (CSPs) require separate approval.
>
> **Authority boundary:** Public reference knowledge is neither observed resource state nor
> permission to act. Packages contain data, not executable rules, prompts, plugins, or deployments.

## Design at a glance

A registered source produces immutable document revisions and append-only source-check receipts.
Both online updates and offline packages enter the existing governed document-ingestion boundary.
Only an admitted collection generation can serve retrieval-augmented generation (RAG), which
retrieves supporting passages before an answer is generated. Each answer pins its generation,
citations, collection times, check receipts, and freshness policy at the answer's evidence cutoff.

## Design revision

| Initial approach | Critique | Revised decision |
|------------------|----------|------------------|
| Use one document timestamp | A recent import can disguise old source material; an unchanged check is not a download | Separate source, collection, check, package, import, activation, and answer times |
| Replace the live index on a timer | Partial downloads, unsafe content, and changed applicability become immediately visible | Collect candidates; verify, review, and atomically activate a bounded generation |
| Trust a signed archive | A signature does not establish source truth, internal approval, or freshness | Independently established trust, exact-content verification, local security review, and current read gates |
| Report the newest date across results | One recent passage can hide an old dependency | Per-claim citations and the weakest required evidence determine answer eligibility |
| Wait for a refresh while answering | An offline source can leave the conversation waiting indefinitely | Return an explicit as-of answer or terminal refresh-required result; track refresh separately |
| Report atomic index commit as verified success | A transaction cannot independently observe its own committed effect | Keep the generation unavailable during readback; publish visibility and terminal success only after exact independent persisted-index verification |

## Source registry and scope

`SourceRegistryRevision` is reviewed, versioned deployment configuration. Only a
designated source owner can request changes; independent security approval admits new origins,
licenses, access modes, and wider collection scopes. A package cannot edit this registry or its
trust policy. Generic schemas and reviewed public-source templates can ship upstream; private
knowledge, access lists, deployment values, and approval identities remain outside this repository.

- **Identity:** CSP, native resource type, canonical URL, source revision when available, and locale.
- **Applicability:** service generation, SKU, API version, region, deployment mode, feature status,
  and effective interval. Missing conditions remain unknown, not universal applicability.
- **Collection policy:** allowed HTTPS origins and paths, redirect policy, source owner, collection
  scope, refresh profile, retention, byte/page budgets, and manual or pre-authorized activation.
- **Rights:** record storage, embedding, internal transfer, and redistribution permissions separately.
  Reference-only sources cannot silently become full-text offline packages.
- **Coverage:** track registered, fetched, admitted, fresh, failed, and unsupported topics per resource
  type. A schema inventory or successful crawl is not proof of complete operational knowledge.

Example: the [Azure API Management (APIM) network requirements](https://learn.microsoft.com/en-us/azure/api-management/virtual-network-injection-resources)
distinguish Developer/Premium from Premium v2. Chunks inherit that distinction, parent headings,
table headers, footnotes, and exceptions; type-name similarity cannot override applicability.

## Time and evidence records

| Field or record | Meaning |
|--------------------------|---------|
| `DocumentRevision` | Immutable source identity, raw SHA-256, normalized SHA-256, section coordinates, applicability, and extractor version |
| `source_updated_at` | Nullable publisher-declared modification time; not an independently verified collection time |
| `collected_at` | Time the origin body was actually fetched, attached to an immutable fetch receipt |
| `SourceCheckReceipt` | Source and request identity, selected content digest, UTC check time, outcome, validator binding, collector identity/version, and provenance digest |
| `last_successful_check_at` | Projection of the latest admitted receipt confirming that the selected body still matches the source |
| `last_attempt_at` | Most recent attempt, including failure; never a freshness renewal |
| `package_created_at` | Time a signed knowledge release was assembled; preserves every source timestamp |
| `imported_at`, `activated_at` | Local arrival and visibility-transition times, recorded independently |
| `answered_at`, `evidence_cutoff` | Trusted answer time and the frozen limit for evidence admitted to that answer |

Use trusted UTC and RFC 3339 timestamps; display the timezone. Missing collection/check provenance,
untrusted clock state, excessive clock skew, or invalid receipt chronology produces unknown or a
hold, never an invented date. A missing publisher modification date alone is acceptable: a verified
fetch/check can establish what the source served, but not when its author changed it.

A successful full-body fetch of identical bytes adds a fetch/check receipt without rebuilding
chunks. HTTP 304 adds only a check receipt. It is valid only for the exact origin, representation,
and request validator already bound to an available complete body; otherwise perform a bounded full
fetch or record unknown. Preserve ETag strength, Last-Modified, request binding, and response outcome.
Record the equivalence basis: a weak/date validator is a server assertion, not byte equality.
Operational checks require a strong validator or a full-body hash comparison; otherwise fetch fully.
Periodic unconditional fetches, by default every 30 days, detect unreliable cache validators.

Discovering a different body creates a candidate; it never refreshes the old body's check time.
Historical answers retain their original receipts even after a later identical-body fetch.
Mirror synchronization, repackaging, signature renewal, import, indexing, and rollback do not renew
source freshness. A mirror needs trusted upstream check receipts, not only a local mirror mtime.

## Refresh and answer policy

The following profiles are deployment policy choices, not freshness guarantees. The default
contract uses the operational profile; deployments approve any changes. A day means 24 hours; monthly means
30 days rather than an ambiguous calendar month.

| Profile | Example topics | Check interval | Maximum unverified age |
|---------|----------------|----------------|------------------------|
| `operational` | networking, DNS, quotas, SKU constraints, security configuration | 7 days | 30 days |
| `reference` | service concepts and relatively stable architecture explanations | 30 days | 90 days |
| `advisory` | explicitly enabled security advisories and urgent deprecations | 1 day | 7 days |

Compute age from the selected revision's admitted `last_successful_check_at`, not its import time.
Keep freshness, connectivity, update availability, admission, and index visibility as independent
axes. A disabled collector does not change any threshold or make old content fresh.

| Freshness | Condition | Answer behavior |
|-----------|-----------|-----------------|
| `fresh` | Age is below the check interval | Explain with dates and citations; say checked-as-of, not live-current |
| `refresh_due` | Age is at least the interval but below the maximum | Queue an authorized check; allow an explicitly dated explanation with a refresh warning |
| `stale` | Age is at least the maximum | Historical/reference explanation only when access and admission still permit it; no current operational conclusion |
| `unknown` | No adequate receipt or trusted time | Return the missing evidence and a review/refresh requirement |

Known newer content sets `update_pending` and prevents a current-guidance claim even if the old
receipt is recent. Query-purpose policy can require freshness sooner than these ceilings. A request
for live-current guidance needs a qualifying new source observation, not merely a `fresh` badge.
If that observation is unavailable, return a terminal `refresh_required` or `evidence_unavailable`
result with an optional separately labeled historical explanation; do not wait for the next cycle.
Partial answers identify supported claims and missing dependencies instead of implying completeness.

Source staleness does not mean malware, revocation, or deletion. Conversely, revoked, integrity-failed,
access-denied, or admission-expired material never becomes eligible just by labeling it historical.
Freshness cannot repair a failed trust or access gate, and a valid signature cannot repair stale
evidence. The most restrictive applicable gate determines use.

## Connected collection

Use a bounded scheduled sweep, not an additional always-on polling service. A daily due check and a startup
catch-up enqueue sources whose successful-check age reaches the profile interval; daily execution
does not mean every document is downloaded daily. Sources with no prior receipt are due immediately.
Public, approved-mirror, and offline modes are explicit per source; network reachability is not
permission. Source access and any billed model use need separate, current authorization.

1. Claim a due source with a durable lease, expected policy revision, and stable attempt key.
2. Enforce origin/path allowlists, TLS, redirect and DNS checks against server-side request forgery,
   plus per-source/global request, page, byte, and concurrency budgets. Do not follow document links
   outside registered scope, load scripts/external images, or treat retrieved text as instructions.
3. Fetch conditionally, compare hashes, and retain immutable observations. Preserve paragraph,
   table, heading, applicability, and source-section boundaries when normalization is required.
4. Stage changed revisions, source differences, coverage gaps, and security observations. Reuse
   unchanged approved artifacts inside the same collection and access boundary only.
5. Request the shared admission and activation flow. Collection success is not activation success.

Initial job budgets are 30 seconds per request, 15 minutes per run, and 2 minutes without progress,
subject to measured capacity and stricter deployment policy. Checkpoint completed items. HTTP
429/503, a deadline, or lost authority ends the affected attempt; later scheduled attempts respect
Retry-After, bounded backoff, jitter, and a configured failure ceiling that requires operator review.
There is no tight retry loop and failures never advance the successful-check clock.

| Observation | Durable outcome |
|-------------|-----------------|
| Unchanged body or valid 304 | New audited check receipt; unchanged chunks and embeddings |
| Changed content, applicability, rights, or extraction semantics | New review candidate; current generation is not overwritten |
| Authentication failure, timeout, or incomplete listing | Failed or partial run with exact gaps; no inferred source deletion |
| 404/410 or removed listing entry | Deletion candidate; require authenticated complete-listing or independently confirmed withdrawal evidence before tombstoning |
| Confirmed security revocation | Prompt governed suppression of affected active references and caches, with audit |

A partial run can stage its successful candidates, but default activation requires every declared
target in that update scope to reach a verified outcome. A smaller scope needs a new reviewed
manifest; it is not silently manufactured after failure. The last-known-good generation remains
available only under its own current access, freshness, and admission gates.

## Offline knowledge package

A knowledge release is an independently versioned, data-only artifact, separate from the application
deployment kit and rule catalog. Version 1 uses complete, bounded packages per selected collection
or service group. Delta delivery is later work: it must pin an accepted base digest and the exact
resulting full manifest, with explicit additions, replacements, and tombstones.

| Package component | Required evidence |
|-------------------|-------------------|
| Signed manifest | Schema, release identity/sequence, creation time, source-policy reference, reader compatibility, exact file list, size, media type, and SHA-256 per entry |
| Source and normalized content | Licensed original snapshots where permitted, canonical URLs, sections, applicability, lineage, collection times, and normalizer versions |
| Check receipts and coverage | Per-document source-check outcomes/digests, collected/check-time ranges, failed and excluded items, and an explicit bounded coverage denominator |
| Review material | Source/license inventory, machine-readable differences, changed constraints, scan provenance, and human-readable review summary |
| Optional numeric embeddings | Exact input hashes, model/revision, dimensions, chunker configuration, and finite-value/schema validation |
| Withdrawal evidence | Explicit reviewed tombstones; omission from a package is not permission to delete |

Do not include executables, model weights, plugins, executable prompts, SQL, serialized object
loaders, database/index dumps, or executable rule/ontology declarations. Import uses a dedicated
purpose-specific package parser; it does not enable arbitrary archives in the upload service.
Signatures authenticate the producer's assertions and exact bytes, not the publisher's truth.

Verification uses an independently provisioned trust root and delegated knowledge-release identity.
Do not trust keys, new origins, approval claims, or relaxed limits supplied by the same package.
Reuse the principles of the [offline trust ceremony](../../runbooks/offline-trust-ceremony.md), with
separate knowledge-artifact purpose binding. Production trust bootstrap remains an implementation
prerequisite, not a capability established by this plan.

Verify signed metadata, hashes, closed file sets, compatibility, expiry, and anti-replay sequences
without network access. Reject path traversal, absolute paths, symlinks/hardlinks, duplicate or
colliding names, extra entries, decompression bombs, and unsupported content under existing parser
ceilings. Trust rotations/revocations travel through separately governed trust updates; a document
package cannot renew its own trust. Show the last trusted revocation-information time explicitly.

Expired update metadata blocks new admission or activation. Already admitted content follows its
local admission validity, revocation policy, access, and source-freshness limits; package expiry
does not rewrite collection dates or automatically revoke an otherwise valid historical record.
Unavailable required revocation evidence blocks the affected use rather than assuming no revocation.

## Internal review and activation

1. **Quarantine:** accept the sealed package and record arrival, transfer identity, and digest.
   Arrival grants no search visibility and makes no external fetch.
2. **Inspect:** verify the trust chain and every entry; run internal malware/content checks with
   policy-approved scanner and signature-data versions. Stale/missing security prerequisites hold
   the package. A producer's scan report does not substitute for internal review.
3. **Prepare review:** compare with the active generation and present changed sections, rights,
   applicability, dates, gaps, and withdrawals. A security reviewer independent of the requester
   accepts or rejects the proposed content scope.
4. **Build privately:** the governed worker builds an inactive index over accepted content. Preserve
   approved normalized bytes or request new review if transformation changes their meaning. Optional
   imported vectors require the exact approved query embedder; otherwise re-embed the whole affected
   index with an available approved internal model, or use explicitly permitted lexical-only search.
   Never mix incompatible vector spaces or fetch a model from the internet as a fallback.
5. **Approve exactly:** the final authorization binds package/content digest, index-input digest,
   destination collection, audience, purpose, policy revision, reviewer, expiry, and expected active
   revision. Recheck these and current scanner/trust evidence at activation, not just at import.
6. **Activate:** compare-and-swap the active collection pointer under a logical-target lock after
   admission, required approval, dry-run, and durable audit intent. Never expose a partial generation.
7. **Verify:** an independent authorized readback confirms the active generation and expected
   searchable/excluded citations. Only this closes success; index-build completion alone does not.

The same gates govern online candidates. Manual independent activation is the initial default.
Unchanged check observations may be admitted under the approved source-check policy without content
reapproval. Automatic content activation requires explicit bounded standing authorization and a
separately tested, shadow-evaluated promotion; enabling a collector grants neither.

Failed candidates leave the valid active generation intact. Failed activation/readback invokes a
tested rollback to an eligible prior generation or an unavailable state if no safe target exists.
Rollback is a new audited activation with a higher activation sequence; it neither lowers release
trust high-water marks nor resurrects revoked content. Preserve old timestamps and citation identity.
Retention, legal holds, tombstone-first visibility removal, and purge follow the existing
[document lifecycle](document-lifecycle-governance.md), not an independent cleanup mechanism.

## Ownership and storage boundaries

Reuse the [document-ingestion ownership map](document-ingestion-agent-ownership.md). Huginn owns
ingress, Heimdall inspection facts, Forseti admissibility, Var human approval, Muninn indexing,
Saga audit, and Vidar recovery. Mechanical workers apply Muninn index commands and governed recovery
commands with document-store permissions only. No collector, importer, Console, or worker gains
Thor's managed-resource identity; documents do not become `ActionRun` requests.

Extend existing service-owned metadata, object storage, and PostgreSQL search storage rather than
introducing a new always-on service. The ingestion API owns intake records, the document worker owns
content/index artifacts, and Core owns agent decisions and freshness policy evaluation. Typed events
carry revisioned references, never shared mutable workflow state or document bodies. Operator API
and Console expose authorized projections and requests only. Durable changes retain stop conditions,
tested recovery, bounded impact, dry-run, lock, idempotency, two-phase audit, and effect verification.

## Answer and operator experience

Cloud provenance in the governed evidence contract binds each material claim to source URL and section, document
revision, fetch/check receipt, collection generation, answer cutoff, and freshness-policy revision.
Authorize and filter candidates before ranking; recheck active/admitted/revoked state before output.
Use exact resource/applicability filters plus lexical and optional semantic retrieval. If source
conditions or required dependencies are unknown, do not infer compatibility from retrieval scores.

Server-owned rendering always shows collection date, last successful source check, freshness status,
and provenance. Package/import/activation dates are separate details, not substitutes. Multiple
sources retain per-citation dates; summarize their range and weakest required status, never only the
newest date. State the actual retrieval mode, including lexical-only limitations. Historical answer
receipts stay immutable; reopening them rechecks access and adds any present-day warning separately.
Offline citations open stored source sections; external URLs remain inert provenance labels.

Example, with synthetic dates: "Collected 2026-08-25; source checked 2026-09-14, unchanged.
This explanation reflects that source check, not a live observation of your APIM instance."

Example, with synthetic dates: "Collected and last checked 2026-08-01; imported 2026-09-10.
At 2026-09-14 this exceeds the operational profile's 30-day limit. Historical reference only;
current network requirements need an approved update." Import does not hide 44 days of source age.

The knowledge workspace should show source mode, policy, active/candidate releases, collection/check
dates, next due time, latest attempt outcome, review backlog, package trust, and collection coverage.
Expose separate refresh, export, inspect, review, activate, and rollback requests with current
role-based access control (RBAC).
Track overdue/stale fractions, changed/unchanged/failed counts, review latency, verification failures,
storage/embedding cost, retrieval quality, and held answers. Notifications are bounded and deduplicated.

## Dependency-ordered delivery plan

### Implemented v1 boundary

The ingestion API owns source checkpoints, append-only check receipts, release sequence reservations,
and authenticated status, refresh, unsigned review export, package inspection/import, collected
candidate staging, and rollback requests. Its existing host wakes a bounded sweep daily; only due
online sources run. A restart repeats the due check, not previously successful downloads.

Each bounded collection release is one immutable governed document version. This reuses the existing
Huginn, Heimdall, Forseti, Saga, Var, and Muninn chain rather than creating a second approval system.
`cloud_reference` requires independent review even after a valid signature. Source bodies and index
rows commit behind expected-version fencing. A pending generation is unavailable while a separate
read-only connection verifies its exact active identity and every persisted chunk against the sealed
source. A second fenced transaction publishes chunk visibility, availability, and terminal audit.
Failure automatically contains the pending generation as unavailable; it never reauthorizes a prior
version. Rollback creates a higher-sequence reviewed request from a still-admissible retained version,
preserves dates, and cannot restore a declared withdrawn source.

V1 packages are canonical JSON capped at 16 MiB, not general archives. They include exact UTF-8
source/normalized content and provenance, with a purpose-bound Ed25519 signature and independently
installed trust. The offline CLI inspects or assembles a detached external signature; it never reads
a private key. V1 intentionally uses lexical-only cloud retrieval and contains no embedding payload.
Extraction retains whole heading-bounded sections, including tables and footnotes. A section plus
its provenance exceeding 8 KiB is held instead of silently slicing away applicability or exceptions.
`FDAI_DOCUMENT_RETRIEVAL_MODE=lexical` also removes document-service embedding startup probes.

The Console Knowledge overview exposes authoritative date ranges, source outcomes, review/import,
and owner-only rollback requests. The semantic answer renderer preserves dates through redaction;
typed semantic targets use exact current-turn source spans for provider, resource type, generation,
SKU, API version, region, and deployment mode. Missing conditions never become compatibility claims;
the canonical `cloud_as_of` facet requires fresh matching evidence and `cloud_current` terminates
with a new-observation requirement, without fetching during the answer. RCA holds stale, pending,
or unbound applicability evidence. Missing source/trust policy is unavailable, never
a test-key or sample-data fallback. Follow the [operator procedure](../../runbooks/cloud-resource-knowledge.md).

The remaining target behavior is deliberately not claimed: automatic prior-generation reactivation,
independent production effect receipts, broader aliases for natural-language applicability,
mirror-specific upstream proof, full online source enrollment, and optional embedding/delta delivery
need the evidence and decisions recorded in the implementation ledger.

| Work package | Depends on | Deliverable and observable exit |
|--------------|------------|---------------------------------|
| K1: Contracts and policy | Design/security agreement | Typed registry, revision, receipt, release, approval, and answer contracts; fake-clock tests cover 7/30-day boundaries, import non-renewal, 304 binding, and unknown time |
| K2: Connected collection | K1 | Azure APIM plus reviewed network dependencies; conditional/due collection, restart checkpoints, exact partial outcomes, and no deletion on listing/auth failure |
| K3: Offline artifact and trust | K1 | Complete data-only package, independent trust bootstrap, content inventory, offline verifier, and internal review receipts; tamper, replay, expired trust, and unsafe archive cases fail |
| K4: Shared admission and activation | K2 and K3 | Existing agent/worker integration, inactive generation build, exact approval, atomic swap, independent readback, revocation, and tested rollback with no executor authority |
| K5: Retrieval and operator surfaces | K4 | Dated bilingual answers, applicability filters, mixed-source status, no-network lexical/embedding modes, freshness/settings projections, and revision-safe requests |
| K6: Acceptance and staged expansion | K5 | Composed connected and egress-denied drills; publish bounded coverage and failure evidence before adding service groups or enabling automated activation |

K2 and K3 can proceed independently after K1; shared contracts and K4 integration stay serial.
Start with APIM and its VNet, NSG, DNS, and private-network dependencies, not an all-Azure claim.
Non-Azure adapters, delta transport, and broader automated activation are separate later decisions.
No delivery dates are promised before the source inventory, legal review, trust prerequisites, and
measured processing cost are known. The [implementation ledger](../../roadmap-implementation/interfaces/cloud-resource-knowledge-lifecycle.md)
records implementation separately from this plan.

### Acceptance matrix

| Scenario | Required result |
|----------|-----------------|
| Weekly/monthly threshold, exact boundary, process restart | Deterministic due/stale state; no duplicate active job or freshness renewal on retry |
| 304, same-body 200, changed-body 200, invalid validator | Correct separate receipts; only changed content needs a new index; old citations remain reproducible |
| Partial crawl, empty listing, login page, 404, 429/503 | Explicit gaps/hold, bounded attempts, retained eligible prior generation, and no mass deletion |
| Old package imported today; valid signature but old source | Original dates and correct stale warning; no current operational conclusion |
| Modified entry, substituted key, unsafe archive, expired trust or scanner data | Rejected/held before visibility; no authority or external fallback |
| Approval expires, policy changes, concurrent activation, process loss | Revalidation and fenced transition; at most one active generation and durable recovery |
| Known newer version, revoked source, rollback, active query/cache | Pending update visible; no revoked hits, mixed generations, stale cache escape, or trust rollback |
| Different SKU/API generation, multiple evidence ages, missing internal embedder | No incompatible answer; per-source dates and explicit held/lexical-only outcome |
| Egress-denied import, indexing, retrieval, and citation opening | Zero external DNS/HTTP/model calls; local stored citations work under access policy |

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery scope and remaining evidence | [Implementation ledger](../../roadmap-implementation/interfaces/cloud-resource-knowledge-lifecycle.md) |
| Admission and retrieval access | [Document ingestion](document-ingestion.md) |
| Indexing and recovery responsibility | [Document ingestion agent ownership](document-ingestion-agent-ownership.md) |
| Retention and deletion | [Document lifecycle governance](document-lifecycle-governance.md) |
| Rules versus narrative retrieval | [Manual distillation](../rules-and-detection/manual-distillation.md) |
| Network and application-kit boundaries | [Disconnected deployment](../deployment/disconnected-deployment.md) |
| Provider portability | [CSP-neutrality contracts](../architecture/csp-neutrality.md) |
