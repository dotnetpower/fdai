# Shared Contract Runtime

This reference describes the semantic channel, contextual selection, logical-topic,
execution-venue, compatibility, and image contracts owned by `fdai_service_contracts`.

## Semantic turn envelopes

Version 1.2 of the existing Operator/Core envelopes adds one bounded semantic-turn request and one
evidence-bound terminal result. The request pins authenticated roles, session ordering, purpose,
deadline, and idempotency. An answered result requires exact release, manifest, plan, execution
receipt, and evidence references. The SDK rejects semantic downgrade to N-1 instead of dropping
those fields. Runtime publication and consumption remain service-owned implementations, and the
Operator bridge supervises distinct terminal-projection and progress topics.

Operator continuation lookup materializes result candidates for the exact session and request
candidates for the exact outbox namespace and principal before joining them by `request_id`. The
bounded candidate sets preserve lineage checks without expanding the PostgreSQL join across
unrelated `state_kv` rows.

## Contextual selection

Semantic-turn requests preserve a typed screen or resource-group selection with an opaque
server-issued token. Operator resolves the token against the authenticated principal, ordinary
lowercase role scope, purpose, exact release, source generation, completeness, and id set, then
recomputes the selection digest before Core compiles an exact `Resource.id` scope for
`query.contextual_resources`. A client-forged or recomputed id, missing-after-restart token, or
scope mismatch is typed unavailable rather than a fallback to the principal-visible collection.
No context field grants approval or execution authority.

Explicit utterance predicates are intersected with the token's set, and an incomplete object-only
contextual table holds the semantic turn instead of becoming an answered claim. This hold is
limited to contextual resource plans; other bounded query tables continue to return their explicit
truncation state. The contextual FunctionType carries its opaque selection token as a scalar schema
input while the object-valued query result remains dependency-only, so a disconnected model node
cannot invoke the specialized read.

Operator instance projections issue the token from the authenticated principal and active
generation, while truncated projections omit the identity entirely. The shared scope digest uses
lowercase ordinary roles (`reader`, `contributor`, `approver`, or `owner`) and rejects
`BreakGlass`. Exact id predicates use batches of at most 128 ids and omit relationship
materialization and relationship-completeness gating for these object-only reads. The wire contract
permits a conservative bounded 512-id context envelope; the general ObjectSet and store limits
remain 1,000. The context contract rejects mixed incident, screen, and resource-group identities,
while exact selection reads retain the source-generation receipt. The same 512 bound is enforced
by the Operator/Core schema, so oversized client context cannot enter planning. The bounded
semantic query JSON envelope remains within its existing byte limit for the 512-id selection
without removing the existing row and byte limits on ordinary outputs.

## Topics and execution venue

The SDK owns the logical-topic marker and deterministic consumer-group derivation used when the two
semantic channels share a physical Event Hub. Core and Operator keep separate adapters, codecs,
identities, logical topics, and offset groups; neither imports the other's implementation. The same
contract exports the canonical physical-topic default used when targeted Terraform state has not
yet materialized newly declared outputs.

The SDK owns the `notification-delivery-receipt` wire schema and canonical logical topic. Operator
authenticates and publishes the observation over the existing multiplexed physical topic; Core
alone applies it to an already accepted delivery. This contract grants no notification target or
execution authority.

The SDK also owns the WARA shadow-assessment topic and Operator consumer-group identifiers. Core
publishes no-authority assessment results through that topic, and the independent Operator service
validates exact active-control coverage before replacing its read projection. The shared contract
contains wire identifiers only; it grants neither service provider-read or execution authority.

The SDK owns the execution-venue contract: the one resolver for `FDAI_EXECUTION_VENUE` and the one
table of venue-selected capability flags. It lives here rather than in a service because every
process resolves the same variable, and an independent service cannot import the core control
plane. `fdai/runtime/venue.py` re-exports it and declares no binding of its own.

## Compatibility and images

The five service distributions use deployable `0.1.2` images as N-1 and `0.1.3` as N. Their
existing contract-set `1.0.0`/`1.1.0` matrix remains the cross-process compatibility boundary.
Content-addressed live evidence also binds the exact service and observation kind and requires
`observed=true`; recomputing a digest cannot convert an unobserved claim into a live receipt.

The package test tree validates SDK behavior. Cross-service N/N-1 and topology checks remain under
[root integration tests](../../tests/integration/). Deployable service images share pinned Alpine
Python, OpenSSL, SQLite, and util-linux runtime packages; the image contract and Trivy gate keep all
six Dockerfiles on exact available versions without known blocked vulnerabilities. The document
worker adds only its owned Tesseract language data and OCR dependencies.

## Related docs

| To learn about | Read |
|----------------|------|
| Repository ownership | [Code Map](../roadmap/architecture/code-map.md) |
| Shared package source | [Service contracts](../../packages/service-contracts/src/fdai_service_contracts/) |
