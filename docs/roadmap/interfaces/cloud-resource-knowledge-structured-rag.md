# Structured cloud-document retrieval

This design extends cloud reference knowledge with reproducible article extraction, bounded
structural excerpts, and separately evaluated bilingual retrieval. It preserves the existing
agent-owned admission and activation path rather than introducing another RAG service.
Composed legacy/text and structured tests exercise the same real agent handlers, including
self-approval rejection, audit-before-index, no Thor execution, and English/Korean source dates.

> **Scope:** Issue #1019 / PR #1047 delivered the original source implementation. Issue #1061
> adds retained-source preparation. Operational qualification, source rights, production trust,
> independent human reviewers and live model evaluation remain under Issue #995. Implementation
> tests and local preparation are not operational approval.

## Design decisions

| Initial option | Critique | Decision |
|---|---|---|
| Change the existing normalizer silently | Signed v1/v2 identity would no longer explain derived chunks | Preserve legacy contracts and extraction; use a distinct structured v3 generation |
| Increase the excerpt ceiling | Larger text does not repair detached table conditions | Retain 8192 bytes including provenance; split only supported structure or hold |
| Approve any signed package | Signature authenticates bytes, not admission or semantic truth | Retain Forseti, Var, Saga and Muninn gates and independent index readback |
| Treat an English source as Korean search support | A localized answer renderer does not prove retrieval | Bind a bounded model-judged query separately from applicability and measure both languages |
| Reindex only when raw bytes change | A new parser, chunk recipe or policy changes meaning too | Track content and processing identities separately from source check time |

## Structured release

Version 3 remains complete, canonical, original-free JSON under the existing 16 MiB ceiling.
It binds one normalized body to bounded structural blocks, inert links, required context,
normalizer identity and an installed deterministic chunk recipe. Source evidence retains exact
collection/check dates and original/normalized digests. It carries no executable recipe, model,
vector, database dump or package-supplied approval. Unknown versions and recipes are rejected.

V1 and v2 signatures and canonical bytes remain unchanged. Their historical normalized content
continues through its original section extractor. New structured readers must be available in
the collector, API/CLI, worker and Core before a structured candidate is emitted operationally.
Collected staging and retained-version rollback both create review candidates and preserve
source evidence, processing identity and admission expiry.
Reprocessing retained source bytes creates a new candidate and separate derivation time; it never
pretends that a source was fetched or checked again.

## Extraction and chunking

The parser is inert and bounded by bytes, nesting, nodes and structural units. Select the actual
article content and exclude active content and site controls. Hidden documentation tabs are not
blanket-deleted. Unsupported structures, unresolved required dependencies and unrepresentable
atomic units hold the complete declared generation. A narrower source scope needs new review.

Preserve heading paths, ordered steps, table headers/units, notices and link destinations.
Paragraphs and table rows are atomic; larger tables may split only with repeated header and
required context. Dependencies are explicit source-local references, not inferred authority.
Table data rows also inherit preceding paragraph/list context from their heading ancestry; the
parser does not guess whether ordinary prose contains an applicability restriction.
Both block-local and document-wide required context reject nested dependencies that the installed
one-level recipe cannot completely represent.
Selecting an article content region cannot silently discard adjacent text, headings or caveats;
all unaccounted non-chrome text holds the candidate regardless of its HTML tag.
Explicit publisher page-action, hidden authorization-template and feedback roles are chrome;
this classification does not discard generic hidden tabs or arbitrary adjacent prose.
Every resulting excerpt includes source identity and remains within 8192 UTF-8 bytes. Text and
metadata limits are independent. Stable IDs bind source revision, block identity, recipe and bytes.
Expanded text is bounded to 16 MiB and 8192 blocks per complete generation, in addition to the
per-excerpt ceiling; repeated required context cannot multiply an input into an unbounded index.

The worker reproduces the sealed chunk inventory only after Saga-audited Var approval and Muninn's
index command. A separate read-only transaction checks the complete persisted row set before the
fenced visibility transition. This proves stored effects, not correctness of the shared parser;
source/claim quality needs independent expected evidence.
Legacy and structured generations share a persisted-effect test matrix covering body/provenance
tampering, changes after readback, invisible pending rows and exact-version/applicability rejection.

## Retrieval and lifecycle

Reuse principal-scoped PostgreSQL lexical retrieval. Exact document references, collection access,
retention, admission, revocation and resource applicability constrain candidates before ranking.
Required context travels with the selected excerpt; a score cannot establish compatibility.
At retrieval, normalized identity, applicability, policy and original collection metadata must
match the admitted source; only a separately verified check receipt may be overlaid.
Missing evidence produces a bounded hold, not an unscoped retry or a live source fetch.
Cloud collection versions use the requested total excerpt budget, capped at eight, rather than
the generic two-excerpt authored-document diversity limit. Access and candidate limits are unchanged.

A schema-validated model-backed query transformation may supply bounded retrieval terms. It cannot
change the original intent, target conditions, audience or authority. Missing transformation
capability remains unavailable; keyword intent routing and automatic external translation are not
fallbacks. English and Korean retrieval outcomes are evaluated separately. Schema 1.2 additionally
requires the exact `semantic-document-query` pack in the prompt replay manifest. The new
`shadow.semantic-document-query` profile is not automatically promoted; older version-pinned
profiles retain their output schema even when the document capability is present. Bragi renders
citations, dates and gaps; T2 retains its separate mixed-model and verification gates.
Source locale uses closed typed validation of `en` or `ko`, never inference from the question.
The frame-model output schema omits Core's accepted-judgment-only query field and its definition.
Internal validation and serialization retain the bound query; model/recovery token ceilings are unchanged.

An unchanged fetch/check preserves collection time and may reuse unchanged derived content.
Normalized bytes, recipe, applicability or rights decisions changing create a material-update
candidate. Observation timestamps alone do not create content changes. A new raw source cannot be
hidden by a stale structured checkpoint: raw identity is compared before derived state.
A processing-only sweep checkpoints retained-byte upgrades under the existing lease, reuses the
old check receipt and reports reprocessing separately. Export requires that durable checkpoint.
Expired or revoked content becomes unavailable before governed retention cleanup; neither a 404 nor an import renews rights
or source freshness. Automatic prior-generation restoration remains deferred.

## Qualification

### Retained-source preparation

An opt-in normalizer `2.1.0` extends the existing v3 representation without rewriting `2.0.0`
checkpoints. The installed `article-blocks-2.0.0` excerpt recipe remains unchanged; processing
identity already binds the normalizer and exact block text. V3 releases containing `2.1.0` require
reader `3.1.0`. Historical reader `3.0.0` and v1/v2 records keep their exact bytes and algorithms.
The ingestion default stays `2.0.0` until a deployment explicitly selects the compatible upgrade.
`FDAI_CLOUD_KNOWLEDGE_NORMALIZER_VERSION=2.1.0` requires explicit v3 output; incompatible or unknown
values fail configuration. This is a reader-compatibility pin, not a capability or authority switch.

| Initial option | Critique | Revised boundary |
|---|---|---|
| Remove all unsupported flags | A missing diagram or ambiguous label can change meaning | Add only explicit inert structures; other dependencies stay held |
| Guess tab names or use the first duplicate ID | Presentation order cannot resolve source identity | Resolve a unique label in the same tab group; referenced duplicate IDs stay held |
| Drop empty tables or split a procedure to fit | This silently changes source accounting or context | Preserve captured headings with an explicit no-data-rows marker; atomic composites retain their byte ceiling |
| Reuse a same-body checkpoint after a metadata/version change | Matching raw bytes do not bind new applicability or rights | Compare immutable source metadata, title and selected normalizer before reuse |

Supported additions preserve `details` summaries and every disclosed body, inert `nobr` text,
source-local tab labels, and complete nested-code/notice composites. Only a unique first direct
summary defines a disclosure label. Explicit notice roles remain required context, including on new
elements; retained descendant conditions are checked before atomic code/table rendering.
Header-only tables describe the captured representation, never proof that a resource has no properties. Arbitrary table spans,
unlabelled or ambiguous tabs, required unfetched media and oversized atomic context remain holds.

A separate local review command reads an explicit bounded manifest of retained snapshots. It
verifies original/normalized file hashes, emits new original-free candidates and per-source
processing/hold records, and never creates registry approval, a signature, an active index or a
model answer. Paths are no-follow and confined to the selected input root; output is exclusive and
private. Source, output and total-byte ceilings plus per-source/total deadlines bound the run.
Normalization and complete excerpt measurement share a resource-limited child process. A late
candidate is not published as successful, and a held/unprocessed source cannot claim excerpt metrics.
Deadline regressions separate controlled-clock publication from actual child startup/timeout checks;
a slow host cannot change which boundary a controlled-clock test exercises.
Reported processing time cannot renew collection or successful-check time. A partial run preserves
the complete requested denominator and explicit unprocessed entries, not a smaller successful scope.
Live source/media/model calls, independent reviewer labels, production trust and operating targets
remain separately supplied prerequisites. An OS-isolated local check is identified as local evidence.
The [operator runbook](../../runbooks/cloud-resource-knowledge.md#prepare-retained-sources-without-network-access)
defines the review input, output, limits and exit codes; these files are not signed release manifests.

### Independent answer qualification

Freeze declared source and question scopes before measuring. Report collected, qualified, approved,
indexed and answer-qualified counts separately. Use guide-first collections; large reference tables
and unresolved source rights do not silently disappear from a failed collection.

The initial evaluation target is at least 80 semantic cases with paired English/Korean questions,
separate development and held-out splits, and per-language complete-evidence recall. Critical
unsupported claims and access/authority escapes block qualification regardless of aggregate score.
Reported results bind corpus, questions, exact source revision, recipe and environment. Synthetic
observations cannot become live, independently reviewed or production evidence by relabeling.

Perform at least ten bounded critique rounds. Record hypothesis, reproduction, severity, fix or
false-positive disposition, focused verification and remaining findings. Stop the implementation
campaign only when no confirmed in-scope Medium-or-higher finding remains; external prerequisites
stay explicitly blocked and are not downgraded to satisfy that threshold.

## Related docs

| To learn about | Read |
|---|---|
| Source dates, package trust and existing lifecycle | [Cloud resource knowledge](cloud-resource-knowledge-lifecycle.md) |
| Agent approval and indexing ownership | [Document ingestion ownership](document-ingestion-agent-ownership.md) |
| Implementation and hardening evidence | [Structured RAG ledger](../../roadmap-implementation/interfaces/cloud-resource-knowledge-structured-rag.md) |
