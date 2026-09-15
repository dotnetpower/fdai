# Structured cloud-document retrieval

This design extends cloud reference knowledge with reproducible article extraction, bounded
structural excerpts, and separately evaluated bilingual retrieval. It preserves the existing
agent-owned admission and activation path rather than introducing another RAG service.

> **Scope:** Source implementation is authorized under Issue #1019. Operational qualification,
> source rights, production trust, independent human reviewers and live model evaluation remain
> separate prerequisites under Issue #995. An implementation test is not an operational approval.

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
Both block-local and document-wide required context reject nested dependencies that the installed
one-level recipe cannot completely represent.
Selecting an article content region cannot silently discard an adjacent paragraph or caveat;
unaccounted structural body content holds the candidate for review.
Every resulting excerpt includes source identity and remains within 8192 UTF-8 bytes. Text and
metadata limits are independent. Stable IDs bind source revision, block identity, recipe and bytes.

The worker reproduces the sealed chunk inventory only after Saga-audited Var approval and Muninn's
index command. A separate read-only transaction checks the complete persisted row set before the
fenced visibility transition. This proves stored effects, not correctness of the shared parser;
source/claim quality needs independent expected evidence.

## Retrieval and lifecycle

Reuse principal-scoped PostgreSQL lexical retrieval. Exact document references, collection access,
retention, admission, revocation and resource applicability constrain candidates before ranking.
Required context travels with the selected excerpt; a score cannot establish compatibility.
Missing evidence produces a bounded hold, not an unscoped retry or a live source fetch.

A schema-validated model-backed query transformation may supply bounded retrieval terms. It cannot
change the original intent, target conditions, audience or authority. Missing transformation
capability remains unavailable; keyword intent routing and automatic external translation are not
fallbacks. English and Korean retrieval outcomes are evaluated separately. Bragi renders citations,
dates and gaps; T2 operational reasoning retains its separate mixed-model and verification gates.

An unchanged fetch/check preserves collection time and may reuse unchanged derived content.
Normalized bytes, recipe, applicability or rights decisions changing create a material-update
candidate. Observation timestamps alone do not create content changes. A new raw source cannot be
hidden by a stale structured checkpoint: raw identity is compared before derived state.
Expired or revoked content becomes unavailable before governed retention cleanup; neither a 404 nor an import renews rights
or source freshness. Automatic prior-generation restoration remains deferred.

## Qualification

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
