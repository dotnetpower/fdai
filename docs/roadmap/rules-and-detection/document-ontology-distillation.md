---
title: Document Ontology Distillation
---
# Document Ontology Distillation

This document defines how FDAI turns governed operational documents into evidence-backed ontology
change proposals. Model output remains inert: it can identify claims and propose typed graph
changes, but deterministic verification and accountable review decide what can enter an ontology
revision.

> **Authority boundary:** A document can declare intent, ownership, procedures, and historical
> evidence only within its approved source authority. It cannot prove current provider state,
> telemetry, execution permission, or a successful external effect.
>
> **Safety boundary:** Distillation never writes the graph, catalog, policy, or provider directly.
> It produces an `OntologyChangeProposal`; an ambiguous, unsupported, stale, conflicting, or
> incomplete proposal is held for review.
>
> **Customer boundary:** Uploaded documents, extracted text, deployment identities, and proposed
> instances remain in governed deployment storage. Upstream ships only generic contracts,
> deterministic gates, and provider seams.
>
> **Implementation status (2026-08-03):** D0-D4 contracts, claim inventory, strict proposal
> compilation, deterministic gates, review packages, lifecycle plans, and frozen-corpus scoring are
> implemented. D4b adds the canonical `DocumentEnvelope` provenance bridge, structured Office and
> PDF locators, OCR fallback, and synthetic cross-format conformance. D4c adds real-document
> parsing, provider conformance, and annotated public-corpus evaluation. D4b results do not prove
> production extraction quality. D4d adds a tool-free T2 ontology model council with blind ballots,
> deterministic consensus, and bounded disagreement evidence. D5 promotion assessment remains
> evidence-only; no live-shadow evidence or automatic promotion is claimed.

## Design at a glance

The pipeline inventories claims before extraction so omitted statements remain measurable. It then
maps each claim to existing ontology declarations, verifies exact source support and authoritative
external evidence, and stages a reviewable graph diff. Approved proposals create a new immutable
revision; reconciliation keeps accepted intent separate from observed external truth.

```mermaid
flowchart LR
    D[Governed document] --> I[Claim inventory]
    I --> E[Typed extraction]
    E --> V[Deterministic verification]
    V --> P[Ontology change proposal]
    P --> H[Accountable review]
    H --> R[Immutable ontology revision]
    R --> C[Authority reconciliation]
    C --> S[Shadow measurement]
```

## Proposal contract

An `OntologyChangeProposal` is content-addressed and proposal-only. It includes:

- proposal id, source document id, immutable document revision, content hash, and extraction run;
- target ontology release and expected graph revision;
- one add, update, remove, or supersede operation over an object or link;
- exact source evidence with section and 1-based inclusive line range;
- claim authority class, effective interval, and freshness policy;
- bounded entity-resolution candidates and the selected canonical identity, when resolved;
- normalized votes from independent extractors or reviewers;
- deterministic gate receipts, conflict references, and a proposal digest;
- review, projection, reconciliation, supersession, rejection, and rollback lineage.

The lifecycle is monotonic:

```text
candidate -> validated -> review_required -> approved -> projected -> reconciled
                  |              |
                  +-> denied     +-> rejected
projected -> superseded | rolled_back
```

A retry with the same source revision, claim, operation, and target release produces the same
proposal identity. A changed source or target revision creates a new proposal rather than mutating
the prior record.

## Claim inventory

Coverage starts before ontology extraction. A claim inventory records every statement that may
carry operational meaning, including:

- normative terms, thresholds, units, prohibitions, and conditional branches;
- service, workload, resource, environment, and owner references;
- dependency, containment, implementation, and escalation relationships;
- procedures, actions, rollback steps, stop conditions, and expected effects;
- event-time observations, historical incidents, and declared effective intervals.

Each claim ends in exactly one disposition: `mapped`, `ignored_with_reason`, or `needs_review`.
Duplicate claim ids, missing dispositions, overlapping contradictory dispositions, and candidate
references to unknown claims fail validation. Structural heuristics and a model-backed detector may
both propose claims, but the deterministic ledger performs the completeness accounting.

For backward compatibility, each claim retains one primary `ClaimKind` in `kind` and records every
detected semantic class in the ordered `signals` tuple. The inventory recognizes bounded English
and Korean normative, relationship, threshold, and imperative forms. It preserves sentence
boundaries around technical versions and URLs, and removes tags, comments, and source shortcodes
before classification so markup cannot become claim text.

## Authority classes

The source authority controls which proposal operations are eligible.

| Authority class | Document use | Required reconciliation |
|-----------------|--------------|-------------------------|
| `declared_intent` | objectives, ownership, constraints, service maps | approved intent source and effective interval |
| `procedure` | rules, workflows, ActionType candidates | catalog schema, safety invariants, shadow replay, review |
| `historical_evidence` | incidents, outcomes, lessons | immutable case or audit evidence |
| `provider_observation` | resource and topology statements | fresh Inventory or provider observation |
| `telemetry_observation` | metric and health statements | fresh telemetry evidence with event time |
| `execution_authority` | permission or autonomy statements | never granted by a document; approved policy remains authoritative |

Source precedence is configured by authority class and scope, never by model confidence. A lower
authority source cannot overwrite a higher authority source. Equal-authority disagreement remains
an explicit conflict and routes to review.

## Extraction and identity resolution

The extractor receives bounded structural units rather than unrestricted document bytes. It must
return schema-constrained data and treat source text as untrusted data, not instructions.

1. Preserve heading, table, page, slide, cell, and line provenance during extraction.
2. Match only an exact existing ObjectType or LinkType from the pinned ontology release.
3. Normalize identifiers, values, units, polarity, comparisons, and effective time.
4. Resolve entities against stable ids and configured aliases before using fuzzy candidates.
5. Return a bounded ambiguous set when no unique identity exists; never invent an instance id.
6. Propose an inert schema change when no existing type can represent a supported claim.

Exact stable-id matches take precedence and resolve automatically. A configured alias resolves only
when it maps to one known entity in `VerificationContext`; the proposal binds that canonical
identity and records `method: alias`. An alias that maps to multiple entities retains the sorted,
bounded candidate set and produces `review_required`. An unknown add also remains review-only.
Update, remove, and supersede operations require one exact or unique-alias identity. Fuzzy matching
never auto-resolves an identity and remains future review-only candidate discovery. Resolution
method and candidates participate in the content-addressed proposal identity.

## Envelope provenance bridge

Ontology distillation consumes the safety-checked `DocumentEnvelope`; it never reparses uploaded
bytes. The bridge emits one normalized manual line per non-empty structural unit and records the
source format, unit id, and locator for that line. Claim evidence, proposal evidence, review-package
digests, and replay digests all retain that tuple, so a citation cannot drift to another paragraph,
shape, table cell, page block, or speaker note.

Locators use a deterministic grammar and 1-based ordinals:

- **DOCX:** `docx/paragraph:{n}`, `docx/heading:{level}:{n}`, or
  `docx/table:{table}/row:{row}/cell:{cell}`. Paragraph content under headings adds a
  `/context:heading:{level}:{ordinal}` ancestry suffix.
- **PPTX:** `pptx/slide:{slide}/shape:{shape}`, an optional `/paragraph:{paragraph}` suffix for
  multi-paragraph shapes, a `/table:{table}/row:{row}/cell:{cell}` suffix, or
  `pptx/slide:{slide}/notes:{paragraph}`. Single-paragraph shape locators remain unchanged.
- **XLSX:** `xlsx/sheet:{sheet}/cell:{address}` preserves the source cell address and resolves
  bounded shared-string references.
- **PDF:** `pdf/page:{page}/block:{block}` for native text and
  `pdf/page:{page}/ocr:{block}` for OCR fallback.

`StructuralUnit.table_cell_role` is optional and backward compatible. DOCX and PPTX cells use
`header` only when their OOXML table metadata declares a header row; other table rows use `body`.
XLSX cells leave the field unset because a worksheet cell address alone does not prove header
semantics. PDF OCR preserves the provider's positive page/block ordinal and rejects duplicates,
reordering, or output-budget overflow before canonicalizing the locator.

Each PDF page selects exactly one evidence path. Native text wins when present; otherwise the
injected page OCR provider must return bounded cited blocks. Missing OCR, encrypted input, parser
damage, unsupported compression, page/count limits, or extracted-character limits fail closed and
produce no review package. OCR is evidence extraction only and receives no executor identity.
Native parsing uses `pypdf` in strict mode and retains `pdf/page:{page}/block:{block}` locators.
Byte, page, object, unit, and character ceilings remain FDAI-owned boundaries, and library errors
are normalized without including document content.

The frozen synthetic corpus expresses the same operational claims as Markdown, DOCX, PPTX, native
text PDF, and scanned PDF. Conformance compares normalized claims, proposals, and graph operations
while allowing only source-format and locator fields to differ. Release requires 100% critical
claim accounting, zero semantic or citation errors, zero normalized graph differences, at least
0.98 critical-claim recall and entity/link precision, and replay-stable digests for every format.

## Real-corpus quality contract

Synthetic fixtures prove deterministic contracts and citation transport. They do not measure how
well an extractor or model handles independently authored manuals. D4c therefore keeps safety and
quality evidence separate:

- **Structure:** Markdown, HTML-like source, Office, native PDF, and OCR inputs produce bounded
  paragraph, heading, list, table, slide, page, or code units. Markup does not become claim text.
- **Provider:** The upstream default may abstain safely, but a deployment cannot report ontology
  extraction as available until its bound `Distiller` passes the same corpus contract.
- **Corpus:** A versioned manifest pins public source URLs, content digests, licenses, format,
  language, annotated critical claims, and expected object or link projections. Source text stays
  outside the package and repository unless its license permits redistribution.
- **Metrics:** Reports distinguish detected-claim accounting from mapped-claim recall, entity/link
  precision, citation accuracy, abstention, parser rejection, latency, and cost. A deterministic
  replay of zero candidates is safe but does not count as extraction success.
- **Release:** Every required format and language partition meets the thresholds independently.
  An aggregate score cannot hide an unsupported PDF parser, an unbound provider, or a weak Korean
  partition.

`ontology_corpus_gate.py` records integer evidence before deriving rates. Each required
`(source_format, language)` partition keeps case and extraction-success counts, detected and
accounted claims, expected and mapped critical claims, predicted and correct entity/link facts,
citation errors, parser rejections, provider abstentions, replay mismatches, semantic errors, and
latency/cost observations. Missing denominators remain visible; a zero-candidate abstention has a
zero extraction-success rate even when its deterministic replay is stable.

The release assessment uses three decisions:

| Decision | Meaning |
|----------|---------|
| `pass` | Every required partition meets the exact configured thresholds and has latency and cost evidence. |
| `review` | Evidence is missing, extraction abstained, parsing rejected input, or a coverage threshold was not met. |
| `deny` | Extracted output contains a citation, replay, semantic, entity, or link error. |

Reason codes retain the partition key, such as
`pdf:ko:critical_recall_below_threshold`; overall `deny` takes precedence over `review`, and
`review` takes precedence over `pass`. This gate is evidence-only and review-only. A passing result
does not grant execution authority, promote an ontology change, or alter a capability mode.

The public-corpus harness reads a machine manifest under `tests/evaluation/`. Each source entry
pins a stable id, HTTPS URL, SHA-256, license id and license source, format, language, source byte
and line counts, plus at least two critical source-line hashes with expected claim signals. Source
bodies stay outside the repository. The caller chooses a temporary or cache directory.

`scripts/evaluation/document_ontology_public_corpus.py` accepts only the exact source host
allowlist, disables redirects, verifies the final URL, enforces timeout and byte ceilings, and
checks the pinned byte count and SHA-256 before caching. It then runs protection inspection,
standard extraction, the envelope provenance bridge, and claim inventory. Reports contain only
ids, digests, counts, status codes, and partition metadata. They never include source or claim
text. Tests inject a local fetcher and use no network. The default report records the provider as
`unbound`, counts an abstention, and records zero extraction successes; a stable empty replay does
not change that result.

Provider conformance uses prepared `ConformanceCase` values with one explicit
`VerificationContext` and annotated ontology facts. The evaluator invokes the bound `Distiller`
twice for each case, measures both calls through an injected monotonic clock, builds real review
packages, and compares candidate counts, abstention reason, critical recall, entity/link precision,
citation and semantic errors, and replay digests. Tests inject cost evidence separately; an absent
cost measurement remains missing evidence rather than an inferred zero-cost success.

Bindings can implement the optional `DescribedDistiller` Protocol to return a versioned
`DistillerCapabilityDescriptor`. The original `Distiller` Protocol remains backward compatible.
An undescribed binding resolves as unavailable, and `AbstainingDistiller` identifies itself as
abstaining with `provider_unbound`. The pure `resolve_ontology_extraction_capability()` function
reports extraction available only when the descriptor targets the current conformance contract and
every required partition passed. This resolution changes availability only. It cannot enable the
feature, change review-only mode, or grant execution authority.

`DocumentParserPolicy` is one immutable, injectable set of hard ceilings for local parsing. It
limits input bytes, structural units, extracted characters, Markdown tokens and nesting, SGML block
nesting, OOXML member count, expanded bytes, compression ratio, XML member bytes and depth, PDF
pages, objects, raw and decoded content-stream bytes, and OCR pages, units, and characters. The
standard inspector and extractor share the policy. Azure OCR has equivalent immutable source,
response, page, line, and character limits. Duplicate or reordered OCR citations fail closed.

OOXML rejects document type and entity declarations and parses XML through a depth-limited tree
builder. SGML parsing does not resolve external entities. Parser and policy errors use bounded
category messages and never include source text. Markdown, SGML, XML, PDF, and OCR adversarial
fixtures verify the ceilings and sanitized outcomes.

Native PDF extraction remains on strict `pypdf`; FDAI does not implement a PDF decoder. FDAI sums
compressed raw content-stream bytes before requesting decoded data and enforces a decoded-byte
ceiling immediately after each `pypdf` decode, followed by page, object, unit, and character
ceilings. `pypdf` does not expose an in-process callback that can stop decompression at an exact
decoded-byte threshold before allocation. This residual means production extraction of untrusted
PDFs should run in an isolated worker with independent memory, CPU, and wall-time limits. The
in-process checks remain defense in depth, not a replacement for isolation.

The ten remediation rounds for D4c cover structure, claim semantics, PDF, Office/OCR provenance,
identity resolution, coverage and release gates, public-corpus replay, provider conformance,
resource/security bounds, and a final independent critique. Each round adds a falsifying fixture
before its implementation is accepted.

## T2 ontology model council

D4d binds an ontology-aware `Distiller` only when all three capability slots are available:
`t2.ontology.council.alpha`, `t2.ontology.council.beta`, and
`t2.ontology.council.gamma`. They resolve to three distinct OpenAI model families. This is a
single-publisher extraction council, not a mixed-publisher council, and it does not satisfy or
weaken the mixed-publisher quality gate for execution T2. Critical claims use three blind ballots.
A model never sees another vote until every required blind ballot has closed, preventing one answer
from anchoring the others. The council is an internal Norns candidate-generation stage, not a new
agent, authority channel, or execution path.

Runtime binding requires all three resolved capabilities and all three structured-output endpoint
bindings together. Each endpoint binding pins an exact non-null model version, deployment, Entra
authentication, route, API style, and verified resource-reference digest. That digest becomes the
model identity's fault domain; equal digests reveal a shared account or gateway fault domain and
therefore correlated infrastructure risk. Zero council records preserve the default abstaining
distiller for backward compatibility. Any partial, `hil-only`, mismatched, unversioned, non-Entra,
or otherwise invalid council configuration makes ontology extraction unavailable and fails startup
binding. It never borrows the execution T2 pool or degrades the existing execution quality gate.

Each model receives the same immutable claim packet:

- claim id, exact source assertion, source locator, and content digest;
- pinned ontology release, allowed object and link declarations, and bounded entity candidates;
- source authority class and only the properties allowed for the target contract;
- no tools, web access, operator memory, provider credential, or executor identity.

Votes use API-level Azure strict `json_schema` and one fixed 12-field shape. Every field is present.
For `unsupported` and `abstain`, proposal fields and semantics are null and `properties` is empty.
For `propose`, operation, target kind and type, target identity, authority, and semantics are
non-null; object endpoints are null and link endpoints are non-null. The Azure-supported schema
permits nullable fixed slots, while the content-free parser enforces these disposition and endpoint
cross-field rules after schema validation. It also requires sorted, unique proposal properties and
sorted, unique semantic string arrays. The prompt requires exact claim-id and citation-digest echo
and permits only supplied types, identities, endpoints, authority, and property names. A proposal
cannot invent an id, type, link, property name, permission, or external observation. The
canonical link `target_identity` is its resolved `from_identity`, so endpoint choice cannot create
a meaningless model disagreement. The
deterministic reducer compares claim, citation, operation, target kind and type, identity,
properties, numeric values, units, comparators, negation, endpoints, and effective time.

Council outcomes are:

| Outcome | Meaning | Candidate behavior |
|---------|---------|--------------------|
| `consensus` | Every required blind vote has the same semantic fingerprint. | Build one inert candidate and run the existing deterministic gates. |
| `contested` | A majority exists but at least one valid vote differs. | Build no accepted candidate; retain bounded field differences for accountable review. |
| `unsupported` | Every model says the claim cannot map to the pinned ontology. | Keep the claim visible as `needs_review`; never treat it as covered. |
| `unresolved` | No quorum, malformed output, timeout, budget exhaustion, or incomplete context. | Keep the claim visible as `needs_review`. |

All three configured blind ballots are required. If any model times out, fails, exceeds budget, or
returns an invalid vote, the round is `unresolved` even when the other two votes agree exactly.

After blind comparison, disputed claims may enter one field-difference critique round. Each model
can `keep`, `revise`, or `abstain` and may cite only the original claim. Raw reasoning and hidden
chain-of-thought are neither requested nor stored. The critique packet contains canonical,
digest-verified alternatives only for disputed fields and canonical baselines for fields that all
three blind votes already agreed on. Critical claims require final 3-of-3 exact agreement. A
2-of-3 result stays `contested`; no Judge model can convert it into consensus.

`OntologyCouncilReceipt` pins model publisher/family/version, deployment binding, prompt and schema
digests, ontology release, claim packet digest, initial and revised vote digests, policy, usage,
latency, outcome, and reason codes. Model failure text and source text never enter the receipt.
Any model, prompt, schema, ontology, or council-policy change invalidates prior conformance evidence.
The distiller conformance `binding_version` is the deterministic digest of the policy and all three
model identities, while the policy digest includes the prompt and schema digests. A changed model,
prompt, schema, or policy therefore cannot reuse an earlier conformance pass.
Availability is resolved per format and language partition and remains false when the council is
unbound, same-family-only, over budget, stale, or below a corpus threshold.

## Verification gates

The verifier evaluates one proposal without calling an executor or mutating a source.

| Gate | Required proof | Failure outcome |
|------|----------------|-----------------|
| Shape | schema, enum, line range, digest, and target release are valid | `denied` |
| Grounding | cited text exists and supports the normalized claim | `denied` |
| Claim accounting | claim exists and has exactly one disposition | `denied` |
| Semantic fidelity | polarity, comparison, number, unit, scope, and time are preserved | `review_required` |
| Identity | one canonical target is proven | `review_required` |
| Authority | source may assert this fact class for this scope | `denied` or `review_required` |
| Conflict | precedence is deterministic and unresolved ties remain visible | `review_required` |
| External truth | provider or telemetry statements have fresh authoritative evidence | `review_required` |
| Safety | rules, workflows, and actions satisfy their complete safety contracts | `denied` |
| Coverage | every claim has a disposition and critical recall meets the release gate | `review_required` |

Model self-reported confidence is never an authority signal. A computed confidence may summarize
grounding, independent agreement, identity resolution, freshness, and historical performance, but
it can only lower eligibility. Independent model disagreement on normalized critical fields routes
to review.

## Lifecycle and rollback

Document and graph lifecycles stay linked by immutable digests:

- **Revision:** A content or curation change reprocesses only affected claims and proposals.
- **Deletion:** A confirmed source deletion creates bounded tombstone proposals. An empty listing
  over a non-empty snapshot is a suspected source outage and cannot mass-delete graph state.
- **Access change:** A narrower source ACL blocks derived reads immediately and schedules removal
  or re-protection of affected artifacts.
- **Conflict:** A later conflicting source does not rewrite accepted history. It creates a new
  proposal linked to the prior revision and conflict receipt.
- **Supersession:** Approved intent replaces a prior effective interval without changing historical
  decision context.
- **Rollback:** Projection failure or later rejection restores the exact prior graph revision and
  records the failed proposal digest.

Projection and reconciliation are separate. Accepting declared intent can update the governed
intent projection. A provider-observed statement becomes current truth only after fresh external
observation matches it.

## Agent ownership

The existing pantheon owns the pipeline without a new coordinator:

| Stage | Accountable agent | Output |
|-------|-------------------|--------|
| Ingress | Huginn | document event |
| Safety and source observations | Heimdall | bounded findings |
| Admissibility | Forseti | admit, hold, or deny decision |
| Structural index and claim ledger | Muninn | immutable context index |
| Inert proposal creation | Norns | proposal candidate |
| Catalog and ontology lifecycle | Mimir | reviewed change package |
| Human approval | Var | independent approval |
| Conflict arbitration | Odin | arbitration decision |
| Audit | Saga | append-only lifecycle evidence |
| Rollback | Vidar | rollback outcome |

No stage calls another agent directly. Authority-bearing transitions use typed events, and no
document path reaches Thor because graph and catalog changes remain reviewed governance proposals.

## Evaluation and promotion

Evaluation uses a frozen, versioned corpus with licensed or synthetic documents, annotated claims,
expected graph diffs, adversarial instructions, scans, tables, conflicting revisions, deletions,
and source outages. Human annotations record reviewer identity and disagreement resolution.

Release gates are:

- zero unsupported critical claims;
- zero number, unit, polarity, or comparison changes on critical claims;
- 100% critical claim disposition accounting;
- at least 0.98 critical-claim recall and 0.98 entity/link precision on the frozen corpus;
- 100% competency-query, replay, rollback, deletion, and ACL regression pass rate;
- zero authority violations, policy escapes, wrong-target projections, and unverified truth claims.

The initial capability is review-only. A later promotion may consider only low-risk mappings after
at least 30 distinct live-shadow days and 500 eligible reviewed proposals, zero guard violations,
and a Wilson 95% precision lower bound of at least 0.99. Ownership, objectives, constraints, rules,
policies, workflows, ActionTypes, permissions, autonomy, schema changes, conflicts, and ambiguous
identities always require accountable review.

D4d council consensus remains an inert, review-only proposal throughout this lifecycle. It never
writes the graph, grants execution authority, or bypasses the existing deterministic verifier and
accountable review, regardless of conformance or shadow evidence.

## Delivery sequence

| Wave | Deliverable | Exit criteria |
|------|-------------|---------------|
| D0 | Proposal, claim, evidence, authority, receipt, and lifecycle contracts | invalid identity, range, digest, state, and authority fixtures fail closed |
| D1 | Claim inventory and typed extraction adapter | every detected claim receives exactly one disposition |
| D2 | Grounding, semantic, identity, authority, conflict, and coverage gates | adversarial and ambiguity fixtures reach only deny or review |
| D3 | Incremental revision, deletion, ACL, supersession, and rollback planning | outage cannot create mass deletion; replay restores exact revisions |
| D4 | Review package and evaluation report | reviewers see graph diff, source evidence, gate receipts, and unresolved claims |
| D4b | Envelope provenance and cross-format extraction | structured locators survive review; normalized graph diffs match across the synthetic corpus |
| D4c | Real-corpus extraction quality | required format/language partitions pass provider conformance and annotated-corpus gates |
| D4d | T2 ontology model council | blind model votes, deterministic consensus, disagreement evidence, model receipts, and live conformance pass without adding authority |
| D5 | Shadow measurement and limited promotion evidence | statistical and zero-violation gates pass without widening authority |

## Hardening record

Forty-three adversarial rounds cover the proposal path, envelope bridge, real-corpus follow-up,
and ontology model council:

| Round | Focus | Result |
|-------|-------|--------|
| 1 | immutable contracts and replay digests | bounded identifiers, scalar values, and candidate lineage |
| 2 | claim completeness | provider and Korean claims, percent thresholds, fences, exact claim accounting |
| 3 | untrusted model output | source-revision pinning, strict keys, authority-bound identity, size limits |
| 4 | verifier behavior | unknown-link crash, stale revision, comparator normalization, safety denial |
| 5 | entity and link integrity | declared endpoint types, target-resolution binding, operation semantics |
| 6 | conflict and external truth | source revision, UTC time, freshness policy, evidence and conflict provenance |
| 7 | review privacy | source access-policy lineage, exact content digest, package bounds |
| 8 | lifecycle and rollback | projection-only revision changes, exact rollback, duplicate retirement rejection |
| 9 | promotion statistics | typed risk class, as-of cutoff, unique evidence, future-observation rejection |
| 10 | integration boundaries | package invariants, context bounds, correct mixed fence handling |
| 11 | reconciliation isolation | proposal-bound receipts and restored current graph revision |
| 12 | boundary formats | ontology release digest, RFC 3339 UTC evidence, bounded references |
| 13 | executable closure | 156 focused tests, 90.62% branch coverage, Ruff and strict mypy pass |
| 14-23 | envelope and format hardening | locator identity, Office/PDF/OCR fail-closed parsing, semantic equivalence, replay, bounds, and E2E; 238 focused tests and 90.63% branch coverage |
| 24 | structured text | Markdown and SGML block parsing reduced public-corpus units from 6190 to 1299, markup units from 2084 to 21, and fragmented boundaries from 2112 to 169 |
| 25 | claim semantics | multi-signal normative, threshold, relationship, and procedure inventory reached 22/22 annotated public claims |
| 26 | production PDF | strict `pypdf` supports xref and object streams under page, object, stream, unit, and character ceilings |
| 27 | Office and OCR provenance | heading context, slide paragraphs, table roles, XLSX cells, and exact OCR page/block locators survive extraction |
| 28 | entity resolution | exact and unique configured aliases resolve; unknown, type-mismatched, and ambiguous aliases remain bounded and unselected |
| 29 | partition gates | zero-candidate, zero-citation, zero-prediction, missing-format, weak-language, semantic, citation, and replay evidence cannot pass vacuously |
| 30 | public corpus | 11 HTTPS sources are pinned by SHA-256, license, format, language, size, and 22 content-free annotations; source bodies remain outside the repository |
| 31 | provider conformance | real bindings are invoked twice per case and measured by partition; an unavailable or abstaining binding cannot report extraction available |
| 32 | parser security | shared limits cover input, nesting, XML, archive, PDF, OCR, units, and characters; errors remain content-free |
| 33 | independent closure | three adversarial audits closed bounded alias, cache, SGML depth, vacuous gate, memory normalization, and fixture escaping findings; 22/22 annotations, zero parser rejection, zero replay mismatch, 372 focused tests, and 93.51% branch coverage |
| 34-43 | model council closure | partial timeout, stale conformance identity, explicit model and usage receipts, revision failure and field scope, malformed values, family/publisher independence, compromised identity, digest-verified critique, canonical link targeting, and live corpus replay; 290 focused tests and 90.62% branch coverage |

The D4c mechanism and public inventory corpus now close with no verified Medium-or-higher finding.
The upstream `AbstainingDistiller` still yields zero candidates for all 11 manuals, so ontology
extraction availability remains false until a bound provider passes the conformance corpus. The
checked-in public corpus currently covers English Markdown and SGML. Required PDF, Office, OCR,
and Korean provider partitions still need licensed or synthetic annotations before a deployment
can claim those partitions. Untrusted PDF decompression also retains the documented isolated-worker
requirement. These residuals keep the capability review-only and cannot raise authority.

The D4d live check verified all three pinned deployments with Entra-authenticated strict structured
output. Four pinned public Markdown claims, including two object and two link mappings, were each
evaluated twice. The cost-optional assessment recorded 100% claim accounting, critical recall,
entity precision, and link precision; zero citation, semantic, and replay errors; zero abstentions;
and deterministic review-only proposals. Provider-reported usage was recorded for every invocation.
Azure retail pricing did not expose verified meters for these model versions, so the canonical
cost-required assessment and deployment availability remain unpassed until pricing evidence exists.

## Verification matrix

| Concern | Required proof |
|---------|----------------|
| Grounding | Every accepted change resolves to immutable source text and document revision. |
| Completeness | Every critical claim has one disposition and omissions remain visible. |
| Identity | Ambiguous or stale targets never project automatically. |
| Authority | Documents cannot assert current external state or grant execution permission. |
| Security | Untrusted text cannot change prompts, tools, policy, or execution identity. |
| Replay | The same inputs and release produce the same proposal and gate digests. |
| Lifecycle | Revision, deletion, outage, ACL, supersession, and rollback are bounded and audited. |
| Customer isolation | Upstream code, fixtures, and docs contain no deployment document content. |

## Related docs

| To learn about | Read |
|----------------|------|
| Upload protection and governed storage | [Document ingestion](../interfaces/document-ingestion.md) |
| Existing manual compilation pipeline | [Manual distillation](manual-distillation.md) |
| Shared semantic and authority model | [FDAI operating ontology](../architecture/operating-ontology.md) |
| Proposal-only ontology primitives | [FDAI ontology safety infrastructure](../architecture/operating-ontology-platform.md) |
