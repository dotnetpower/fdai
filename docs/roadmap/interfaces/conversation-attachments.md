---
title: Conversation Attachments
---
# Conversation Attachments

This document defines how Slack, Teams, and web chat attach documents and images to an FDAI
conversation without bypassing document safety, authorization, grounding, or ownership-handover
governance.

> Conversation channels never trust payload-supplied download URLs and never put file bytes in a
> model prompt. Every source enters the governed document-ingestion pipeline first. Only immutable
> `doc:<document_id>:<version_id>` citations reach a conversation.

## Design at a glance

All channel types converge on the same document lifecycle:

![Design at a glance. The main stages are Slack opaque file id, Server-authenticated fetcher, Teams opaque attachment id, Web upload session, Ingestion gateway, Malware and protection checks, Text, Office, or optional OCR extraction, Immutable document version and index, Authorized doc citation, Conversation evidence, Ownership draft and governance PR.](../../diagrams/generated/fdai-roadmap-interfaces-conversation-attachments-01.en.svg)

The file source changes by channel. Safety, storage, purpose, citations, retention, and audit do not.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Vendor-neutral attachment metadata | implemented | [`conversation_channel.py`](../../../services/core-control-plane/src/fdai/shared/providers/conversation_channel.py), [`test_channel_gateway.py`](../../../services/core-control-plane/tests/conversation/test_channel_gateway.py) | `ChannelAttachment` and `InboundTurn` enforce bounded opaque metadata. No vendor adapter is implied by these contracts. |
| Explicit attachment purpose | implemented | [`attachment_directive.py`](../../../services/core-control-plane/src/fdai/core/conversation/attachment_directive.py), [`test_attachment_directive.py`](../../../services/core-control-plane/tests/core/conversation/test_attachment_directive.py) | Exact leading directives select handover intent; prose and filenames do not. |
| Channel ingestion gateway seam | implemented | [`channel_gateway.py`](../../../services/core-control-plane/src/fdai/core/conversation/channel_gateway.py), [`test_channel_gateway.py`](../../../services/core-control-plane/tests/conversation/test_channel_gateway.py) | The gateway accepts an injected ingestor and fails closed when one is absent. It is not a concrete protected-ingestion implementation. |
| Slack attachment handoff | implemented | Operator `channel_edge/{slack_ingress,attachment_handoff}.py`; focused handoff, environment, and pipeline checks | The signed adapter retains bounded opaque metadata, discards payload URLs, resolves `files.info` through fixed HTTPS hosts, and streams private bytes into an unnamed bounded spool. |
| Teams attachment handoff | implemented | Operator `channel_edge/{teams_ingress,attachment_handoff}.py`; focused handoff, environment, and pipeline checks | The authenticated adapter retains bounded opaque metadata, discards payload URLs, and accepts only a configured HTTPS resolver, host allowlist, and token audience allowlist. |
| Protected channel ingestion composition | implemented | `fdai_ingestion_api_service/channel_attachment*.py`; Operator `channel_edge/{composition,pipeline}.py`; 28 intake and 236 Operator focused tests | A separate internal ingestion workload owns admission, canonical upload, durable replay, terminal observation, and citation return. Provider bytes never enter Kafka. |
| Channel handoff compatibility promotion | in-progress | `compatibility-manifest.json`; transition certification scope; focused and independent-service compatibility checks | All nine current contracts pass focused compatibility. The retained transition evidence certifies the seven previously deployed edges only; the two attachment HTTP edges remain outside transition certification until new protected N/N-1 evidence exists. |
| Exact Core document retrieval | implemented | `governed_document_reader.py`; `postgres_governed_document_read.py`; `semantic_turn_processor.py`; 377 focused Core and ownership tests | Core reauthorizes every request-bound version, searches only the exact identity set, and requires the terminal result to echo the document-context digest and actual returned citation set. |
| Web chat document references | implemented | Operator `document_refs.py`, `postgres_document_refs.py`, and `factory.py`; Operator migration `20260914_operator_conversation_document_refs.py`; focused Operator and migration checks | The Operator replaces raw refs with a server-owned `web_reference` context before durable semantic publication. A bounded security-definer function preserves document-table ownership and authorizes uploader or reader-group access without granting raw table reads. |
| Web chat inline vision path | in-progress | [`composer-attachments.view.tsx`](../../../console/src/deck/composer-attachments.view.tsx), [`backend-context.ts`](../../../console/src/deck/backend-context.ts), [`conversation_images.py`](../../../services/core-control-plane/src/fdai/delivery/conversation_images.py), [`postgres_conversation_images.py`](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_conversation_images.py) | Console capture, request serialization, bounded image repositories, migrations, and historical rendering exist. The Operator semantic envelope and local narrator currently discard image attachments, and production does not bind the image repository to chat routes. |
| Document image OCR | implemented | [`processing.py`](../../../services/document-processing-worker/src/fdai_document_worker_service/adapters/processing.py), [`production.py`](../../../services/document-processing-worker/src/fdai_document_worker_service/production.py), [`test_ingestion_adapter_readiness.py`](../../../services/document-processing-worker/tests/test_ingestion_adapter_readiness.py) | The document worker binds bounded Document Intelligence `prebuilt-read` when an OCR endpoint is configured and otherwise fails closed. This does not complete channel or inline-chat ingestion. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-14 | implemented | Separated the current nine-contract focused matrix from the retained seven-edge transition certification instead of relabeling historical local and live evidence. | `current change`; compatibility manifest and validators; focused compatibility and independent-service checks; certification-scope negative tests. | Add the two attachment HTTP edges to transition certification only after a protected N/N-1 deployment records exact schema, identity, health, offset, source, image, and topology observations. |
| 2026-09-14 | implemented | Added the private Slack and Teams fetch path, internal channel-intake workload, durable admission and commit replay, hash-bound terminal receipts, exact Web and Core authorization, local and Terraform topology, protected transition guards, and authenticated workload-readiness probing. | `current change`; 93 contract, 28 intake, 236 Operator, 377 Core and ownership, 40 Entra, 2 exact migration, and 345 deployment, workflow, and local-startup focused tests; four ownership-scoped strict mypy checks; changed-file Ruff and generated-artifact checks. | Record protected deployed-runtime evidence after the tenant administrator completes the application-role prerequisite. Complete the separate inline-vision path. |
| 2026-09-14 | implemented | Reconciled the post-decomposition Operator edge with this owner: disabled provider attachments now fail before queue admission, direct queue injection fails before semantic publication, and unsupported enablement fails startup. | `current change`; focused Operator environment, composition, Slack, Teams, and pipeline checks. | Define a versioned handoff to agent-owned document ingestion and bind private vendor fetchers, terminal citation return, and governed runtime evidence. |
| 2026-08-13 | in-progress | Reconciled the design with current contracts, adapters, composition, Console code, and tests without reconstructing earlier provenance. | Current source and focused checks listed in the scope table. | Vendor adapters, protected ingestion, web document resolution, the server inline-image path, and governed runtime receipts remain open. |
| 2026-08-16 | in-progress | Added the bounded `document_refs` request contract and its principal-scoped, fail-closed resolution boundary ahead of semantic processing. | `pytest services/operator-service/tests/test_conversation_document_refs.py` passed 12 focused tests covering syntax and non-canonical UUID rejection, the eight-reference cap, uniqueness, uniform denial, missing-resolver 501, contained resolver failure, and reordered or substituted citation refusal. | Carry resolved citations into the versioned semantic envelope and bind a production resolver over PostgreSQL document metadata. |

### Remaining work

- [x] Implement signed Slack and authenticated Teams inbound adapters that retain only bounded
  opaque attachment metadata and reject it before queue admission while protected ingestion is off.
- [x] Implement private vendor fetchers with server-owned endpoint resolution, credential scoping,
  redirect refusal, host allowlists, and streamed byte limits.
- [x] Compose a concrete channel ingestor through malware, protection, extraction, indexing,
  authorization, citation, and handover paths.
- [x] Add the bounded `document_refs` request contract to the Operator conversation family and
  resolve it through principal-scoped document authorization before semantic processing.
- [x] Carry resolved `document_refs` citations into the versioned semantic envelope, bind a
  production resolver over authoritative PostgreSQL document metadata, and add route-level tests.
- [ ] Complete the server inline-image parser, byte and media validation, repository binding,
  semantic transport, vision narrator input, history metadata, and authenticated retrieval path.
- [ ] Record a protected deployment in which the intake is enabled first, the edge service
  principal receives exactly `Document.ChannelAttachment.Submit`, the authenticated readiness
  probe passes, and one Slack or Teams attachment reaches a query-visible citation.
- [ ] Promote `channel-attachment-admission` and `channel-attachment-receipt` into the transition
  certification scope only after the protected N/N-1 run retains exact seven-kind observations.
- [ ] Record an authenticated Web `document_refs` turn whose exact citations and
  `document_context_digest` are preserved through the Core terminal result.

## Purpose and authorization

### Default evidence

An attachment without a directive uses `knowledge_base`. Attachment-only messages are valid and
return a deterministic protected-ingestion acknowledgement with citations. Ordinary prose that
mentions a handover does not change purpose.

### Ownership handover

Ownership handover requires an exact leading directive:

```text
/handover
/handover transfer Thor and Heimdall ownership
/attach handover
인수인계 문서: Thor 담당자 변경
```

The handover role floor is Contributor. The role check runs before vendor download, so a Reader
cannot spend fetch, scan, OCR, embedding, or GitOps capacity. A successful handover does not call the
narrator. It returns a deterministic review acknowledgement after the existing handover consumer has
created the grounded draft and, when enabled, the governance pull request.

The uploader does not become the owner by uploading. Existing ownership remains intact because the
candidate is additive. A person reviews and merges the Git change before the deployment loads it.

## Versioned service handoff

### Initial design

The initial cross-service option reused the public create, content, complete, and status routes.
The Operator edge would call those routes with its workload token and attach the mapped human
principal in request headers.

### Design critique

That option is not accepted. The public authenticator treats the bearer-token subject as the
upload actor, so it cannot keep the edge workload and attributed human separate. Caller-provided
roles, groups, collection, access, or retention would also make the ingestion API a confused
deputy. Slack and Teams metadata do not provide a trusted SHA-256 before download, while the
canonical upload session requires one. Finally, a response-selected upload URL would introduce an
unnecessary network-destination decision at the edge.

### Revised design

The accepted handoff uses an internal-only workload from the existing Document Ingestion API
distribution. It is another independently scalable process of the same service owner, not another
service distribution or document writer. The public drop-zone routes remain unchanged.

The intake authenticates four identities independently:

1. Slack signature or Teams service token establishes the provider request.
2. The channel principal mapping identifies the attributed FDAI human.
3. The dedicated Operator edge managed identity authenticates the HTTPS caller.
4. The internal intake uses a document-ingestion identity for PostgreSQL, object storage, and
  lifecycle publication. No identity in this path is Thor's executor identity.

The workload token requires the exact ingestion audience, issuer, application identity, and one
attachment-submit App Role. Delegated scopes, group claims, another application, or a human token
do not satisfy this boundary. The request carries the human principal id and principal-manifest
digest only as attribution. Ingestion loads the same versioned manifest independently, resolves
the current roles itself, and requires document Contributor access before admission. The request
cannot supply roles, groups, collection, access descriptor, retention, URL, token audience, or
endpoint.

Ordinary conversation evidence uses `session_ephemeral`, conversation scope, and the deployment's
server-owned attachment policy. A handover directive selects only the requested purpose; ingestion
maps it to a server-owned handover policy and repeats the Contributor check. Collection, reader
groups, storage mode, access descriptor, and retention always come from that policy.

The service contract uses these immutable authority-free records:

| Record | Responsibility |
|--------|----------------|
| `ChannelAttachmentAdmissionRequest` `1.0.0` | Bind the deterministic handoff id, origin digest, attachment ordinal, attributed principal, manifest digest, requested purpose, safe name, media hint, declared size, deadline, and request digest. |
| `ChannelAttachmentAdmissionReceipt` `1.0.0` | Return the accepted policy digest, server limits, expiry, and receipt digest without a URL or storage credential. |
| `ChannelAttachmentCommitReceipt` `1.0.0` | Bind the independently observed size and SHA-256 to the canonical upload, document, and version ids after durable `received` state. |
| `ChannelAttachmentTerminalReceipt` `1.0.0` | Bind the durable commit receipt digest, observed size, SHA-256, lifecycle and index state, and observation time. Return exactly one citation only for an active, available, live-retention version with an active index. |

Each record rejects unknown fields, is immutable, carries `execution_authority=false`, and uses a
canonical content digest. The HTTP major version remains in the fixed internal path. Additive
minor versions retain N and N-1 readers; unsupported versions fail before reservation or content
I/O.

Admission runs before the vendor download. After admission, the edge streams the vendor response
into an unnamed, quota-bound ephemeral spool while computing size and SHA-256. The spool prevents
whole-file memory buffering and satisfies the canonical upload session's required predeclared hash.
The edge then streams the same bytes to the fixed internal HTTPS origin with the admission digest,
content length, and hash. It never follows an intake-provided URL. Missing encrypted scratch or a
cleanup failure keeps the capability unavailable.

The intake derives one stable upload identity per handoff, invokes the existing create and
streaming-content boundaries, and calls the existing completion boundary only after object-store
size and hash agree. Only the ingestion API publishes `document.received`. Network ambiguity is
resolved by reading the handoff status before any retry; the edge never blindly repeats a content
PUT. A replay with the same handoff id and request digest returns the retained state. Reusing the id
with different content or metadata returns a conflict and publishes no new document event.

The status route returns the last durable phase. It replays admission until commit persistence is
complete, then replays the commit until metadata is observable, and returns a terminal receipt only
after both exist. Every terminal observation retains the same commit digest, canonical ids, size,
SHA-256, and purpose. A changed progression fails before a citation is accepted.

If canonical upload completion succeeds before reservation commit persistence, status replay
reconstructs the commit from canonical upload state. It does not require another vendor download or
another content upload.

The edge waits through the intake status surface, not through document-table access. A knowledge
attachment succeeds only when document and index state satisfy the retrieval predicate. A handover
attachment also requires the existing grounded draft projection and, when enabled, its governance
delivery receipt. Timeout, hold, failure, deletion, expiry, or index failure returns no citation and
never starts an inline worker.

Attachment-only turns return the ordered citations in a deterministic acknowledgement. A text turn
uses additive `operator-core-request` `1.8.0` with an ordered `document_context`. Core reauthorizes
every exact version and restricts the governed-document query to that set. One unavailable or
unauthorized reference holds the document lane; it never widens to collection search. The terminal
semantic result binds the document-context digest and can cite only references admitted by that
context. Function evidence derives citations from the source refs actually returned by exact search,
never from the requested set; a missing, substituted, or malformed citation holds the answer.

## Slack download contract

Slack event payload URLs are untrusted and discarded. The fetcher:

1. Accepts only the normalized opaque file id.
2. Reads the bot token from the injected secret provider.
3. Calls the server-configured HTTPS Slack API `files.info` endpoint without credentials, query,
  fragments, or redirects, requires HTTP 200, and stops reading metadata as soon as the configured
  byte cap is exceeded. The API origin must match the fixed metadata-host allowlist and use the
  default HTTPS port.
4. Requires the returned Slack file id to exactly match the requested opaque id.
5. Accepts only a private download URL whose host exactly matches the configured allowlist and
  whose HTTPS port is the default port.
6. Sends the bot token only to that validated host.
7. Disables redirects, rejects invalid or negative `Content-Length`, and enforces streamed-byte
  limits on decoded content.
8. Returns bytes to protected ingestion, which recomputes SHA-256 and checks metadata size.

The Slack app needs the narrow file-read permission required by the selected Slack API. Token values
stay in Key Vault or another `SecretProvider`; they never appear in config, audit, or errors.

## Teams download contract

Teams payload `contentUrl` and `serviceUrl` values are discarded. A deployment supplies a
`TeamsAttachmentEndpointResolver` that maps the opaque id through server-owned Bot or Graph state to
an `AttachmentDownloadLocation` containing a URL and token audience.

The fetcher:

- requires HTTPS and an exact configured host;
- requires the server-resolved token audience to exactly match
  `FDAI_TEAMS_ATTACHMENT_AUDIENCES` before requesting a token;
- rejects URL credentials and redirects;
- requests an audience-scoped token from the injected workload identity;
- streams within the same byte cap as Slack;
- sends no executor identity and accepts no caller-selected audience.

This resolver seam supports Bot Framework, Microsoft Graph, and sovereign-cloud deployments without
letting untrusted payloads select a network destination.

## Web chat contract

The Operator API does not accept multipart files, raw bytes, storage URLs, or channel attachment ids.
The SPA flow is:

1. Create an authenticated ingestion upload session.
2. Upload and complete the file through the ingestion gateway.
3. Poll until the version is `ready` or `ready_with_warnings`.
4. Send `document_refs` with the chat turn:

```json
{
  "prompt": "Summarize the attached evidence",
  "document_refs": [
    {
      "document_id": "<document-uuid>",
      "version_id": "<version-uuid>"
    }
  ]
}
```

JSON and SSE routes enforce a maximum of eight unique references. Production passes the verified
principal and current groups to one bounded PostgreSQL security-definer function. The function
returns only active, available, unexpired `governed_knowledge` versions with an active index, live
retention, collection scope, and `knowledge_base` purpose when the principal is the uploader or a
configured reader-group member. The Operator role retains no raw `document_version` table access.

The resolver must return each requested citation in the same order and exact canonical form,
`doc:<document_id>:<version_id>`. A substituted, reordered, duplicate, or malformed provider result
fails closed before it reaches view context or verification.

Resolved refs enter server-owned view context and terminal verification. Invalid UUID syntax returns
400; a deployment without a resolver returns 501. A missing, unavailable, held, failed, deleted, or
another principal's version returns the same access denial so document existence is not disclosed.

Inline vision images use a separate bounded repository rather than document ingestion. Each stored
image is keyed by the authenticated principal, conversation, and opaque image id. The operator turn
stores only id, display name, and validated media type; it never stores the base64 body. The Console
reads a historical image through authenticated
`GET /me/conversations/{conversation_id}/images/{image_id}` and creates a browser object URL for
display. A different principal, conversation, or unknown id returns the same `404` response. Deleting
the owning conversation cascades to its image rows. Each image also expires after 90 days even when
the conversation remains active; the scheduled user-context retention job removes expired image
bytes independently. A principal can retain at most 1,000 conversation images or 256 MiB, whichever
limit is reached first. Exact retries do not consume quota twice, and a quota rejection returns
`429` before turn metadata is stored. Images remain on a 15-minute pending expiry until the operator
turn is durable, then move to the 90-day expiry. If immediate compensation also fails, the next
upload or retention pass removes the pending bytes after that short interval.

The composer presents a staged image as a fixed thumbnail without repeating its filename, byte
size, or ready label. Pointer hover, keyboard focus, or touch opens a viewport-bounded large preview
through the shared tooltip layer. While normalization is in progress, the tile uses the shared
neutral top-edge shimmer; reduced-motion preference disables that animation. Non-image files and
rejected attachments retain their compact metadata and actionable reason.

## Image OCR

The standard extractor recognizes image signatures before OCR. Without an OCR provider it preserves
the existing metadata-only image version. When `FDAI_OCR_ENDPOINT` is configured, production binds
`AzureDocumentIntelligenceOcr`:

1. Obtain a managed-identity token for the configured Cognitive Services audience.
2. Submit the image to `prebuilt-read` over HTTPS.
3. Validate `Operation-Location` against the exact configured origin, treating the implicit HTTPS
  port and explicit `:443` as equivalent.
4. Poll within configured attempt and time limits.
5. Enforce `FDAI_OCR_MAX_RESPONSE_BYTES` while streaming each poll response and stop before reading
  later chunks, then apply line and character limits to the parsed result.
6. Convert bounded page lines into `StructuralUnit` values with locators such as
   `page:1:line:2`.
7. Reject redirects and normalize identity, transport, malformed, failed, unknown, cross-origin,
  or over-budget failures as OCR provider errors.

A configured OCR failure fails the extraction stage and does not create searchable or handover
evidence. OCR text remains untrusted evidence and cannot redefine instructions or tool authority.

Terraform accepts `document_ocr_endpoint` only with a matching `document_ocr_resource_id` and
document ingestion enabled. It grants the ingestion managed identity `Cognitive Services User` at
that resource only. An empty endpoint keeps metadata-only behavior and provisions no OCR role.

## Production composition

The standalone Operator edge owns the strict `FDAI_CHANNEL_ATTACHMENTS_ENABLED` switch. Unset or
`0` keeps the capability unavailable and attachment turns return `422 attachments_unavailable`
before queue admission. `1` requires a complete fixed intake origin and audience, dedicated
attachment credential, encrypted absolute scratch path, byte ceiling, principal-manifest digest,
and every enabled provider's endpoint and host policy. Any missing, partial, or mixed local and
deployed identity configuration fails startup before a channel consumer begins.

The configured edge byte ceiling is independent of the intake admission limit. Each vendor stream
uses the lower bound, so an intake policy increase cannot silently widen edge download authority.

The Document Ingestion API distribution ships `fdai-document-channel-intake` as a separate
internal-only Container App and local process. It uses the ingestion database role, canonical
document object store, lifecycle publisher, and durable `state_kv` reservation record. Its live and
ready probes are separate, and readiness closes when an adapter is unavailable or a supervised
outbox task stops. The Operator edge uses separate HTTP pools for provider downloads and intake
traffic, an unnamed temporary file under the configured scratch directory, and one dedicated
audience credential. Vendor attachment names remain leaf names without path separators, dot-only
names, or control and formatting characters. Operator transport and spool mechanics remain in
`attachment_handoff.py`; replay, terminal observation, and semantic context orchestration remain in
`attachment_ingestion.py`.

The intake exposes an authenticated no-op probe at the same audience and App Role boundary as
admission and content. The edge calls this probe before it reports ready. Use this protected rollout
order:

1. Enable the internal intake while channel attachments remain disabled at the edge.
2. On the Entra application that exposes `FDAI_CHANNEL_ATTACHMENT_API_AUDIENCE`, define the
  `Document.ChannelAttachment.Submit` App Role for `Application` members and assign only that role
  to the dedicated edge service principal. This tenant-directory operation requires an authorized
  administrator and is not inferred from Terraform plan approval.
3. Enable attachments on the Operator edge. Startup obtains a token for the exact audience and
  requires the authenticated probe to return `204`. A missing definition, assignment, audience,
  or client binding keeps readiness closed and causes a protected newly-enabled edge rollback.

Enable and disable transitions for the intake and edge are independently guarded, plan-sealed, and
health-verified. The intake should be enabled before the edge. Disable the edge before removing the
intake. Local parity uses an explicit client credential for the same audience and exact App Role;
deployed mode accepts only the configured managed identity and rejects local secret settings.

After protected ingestion completes, the gateway can project actual redacted coordinator
activities into typed channel progress snapshots. This changes presentation only. Attachment bytes,
purpose, authorization, scanning, terminal citation checks, and agent ownership remain unchanged;
no progress text becomes an instruction or evidence authority.
Running revisions show summary text only. Canonical redacted activity evidence appears with the
final confirmed revision after protected ingestion and coordinator completion.
Progress metrics can count truncation and terminal delivery, but they contain no filename, document
id, citation, source reference, collection, channel id, or extracted content.
Teams card-budget activity omission counts as truncation without adding the omitted activity count
or content to metrics.
Teams canonical-answer clipping also counts as truncation without adding answer text or length to
metrics. This includes earlier clipping required by multibyte serialized card bytes. Neither
Teams nor Slack canonical-answer clipping changes attachment evidence authority or durable response
data, and Slack metrics likewise retain no answer text or length.
The channel publisher keeps transport and acknowledgement handling separate from pure rendering;
this structural split does not change protected ingestion or the redaction boundary.

The channel intake completes each canonical upload and publishes `document.received`; it never calls
the processing worker directly. The edge waits through the authenticated status route for the
terminal version produced by the existing event pipeline. The wait has a fixed positive deadline
and bounded polling interval. A timeout returns no citation and does not run an inline worker
fallback.

For a deployed handover, the intake validates the typed draft's upload, document, version, drafted
outcome, and nonempty mappings. It derives the same content-addressed governance key as Core and
requires a matching published receipt with a PR reference before setting
`handover_draft_ready=true`. A missing receipt remains pending; a substituted or malformed receipt
fails closed.

A message with multiple attachments creates one governed `UploadSession` per file. The files keep
independent lifecycle, retention, and audit records; the channel message is not a storage
transaction. If one file is held or fails, the turn returns no citations, while any sibling already
accepted by the pipeline remains visible through document-ingestion operations rather than being
silently deleted. Admission, fetch, commit, and terminal observation run in stable ordinal order
within the eight-file message cap, so returned citations preserve input order and no detached
background poll survives a failed turn.

## Failure behavior

| Failure | Behavior |
|---------|----------|
| Missing vendor fetcher | Reject attachment before ingestion. |
| Reader submits `/handover` | Reject before vendor download. |
| Any attachment metadata exceeds the byte cap | Reject the whole turn before the first fetch. |
| Vendor metadata size mismatch | Reject; no citation. |
| Redirect or host mismatch | Reject before token disclosure or download. |
| Byte cap exceeded | Abort stream and reject. |
| Malware or protected-content hold | Return no citation and do not call the narrator. |
| Agent pipeline misses the terminal wait bound | Reject the turn; never run a worker inline. |
| Intake terminal changes commit digest, ids, size, hash, or purpose | Reject the receipt; return no citation. |
| Workload App Role or audience is missing | Keep the edge unready and block the enable transition. |
| Unexpected failure before attachment completion | Release the message claim, emit a sanitized processing transition, and continue the next queued turn. |
| Session/tool failure after attachment completion | Keep the message claim, return one generic error, and never ingest the same vendor message twice. |
| Cancellation before durable channel delivery | Propagate cancellation and release the message claim; a retry reuses durable attachment status. |
| OCR configured but unavailable or malformed | Fail extraction; no searchable evidence. |
| Web reference malformed | Return 400. |
| Web resolver absent | Return 501. |
| Web version belongs to another principal or is unavailable | Deny access. |
| Duplicate channel message | Existing channel ledger prevents repeated processing. |

The channel gateway emits `attachment.ingestion` transitions for unavailable, rejected, and ready
outcomes without including filenames, source references, document contents, or provider errors.
An unexpected turn failure is isolated to that turn; it does not terminate the Slack or Teams
receive loop.

## Verification

Focused verification covers:

```bash
python -m pytest -q --no-cov \
  packages/service-contracts/tests/test_channel_attachment.py \
  packages/service-contracts/tests/test_semantic_turn.py \
  services/document-ingestion-api/tests/test_channel_attachment_http.py \
  services/document-ingestion-api/tests/test_channel_attachment_intake.py \
  services/operator-service/tests/test_channel_attachment_handoff.py \
  services/operator-service/tests/test_channel_edge_pipeline.py \
  services/core-control-plane/tests/core/knowledge/test_governed_document_reader.py \
  services/core-control-plane/tests/test_semantic_turn_processor.py
```

Current regressions cover request and receipt digests, durable restart replay, content and terminal
hash binding, Slack and Teams destination controls, authenticated workload readiness, cancellation,
handover draft readiness, exact reference budgets, Web resolver denial, Core no-widening retrieval,
terminal citation equality, migration ownership, local parity, and protected deployment rollback.
Deployed provider evidence and end-to-end inline vision tests remain open.

## Related docs

| To learn about | Read |
|----------------|------|
| Document safety and storage | [document-ingestion.md](document-ingestion.md) |
| Conversational channel authority | [operator-console.md](operator-console.md) |
| Ownership draft and merge lifecycle | [agent-stewardship-operations.md](agent-stewardship-operations.md) |
| Durable channel delivery | [durable-conversation-delivery.md](durable-conversation-delivery.md) |
