# Conversation Attachments implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Vendor-neutral attachment metadata | implemented | [`conversation_channel.py`](../../../services/core-control-plane/src/fdai/shared/providers/conversation_channel.py), [`test_channel_gateway.py`](../../../services/core-control-plane/tests/conversation/test_channel_gateway.py) | `ChannelAttachment` and `InboundTurn` enforce bounded opaque metadata. No vendor adapter is implied by these contracts. |
| Explicit attachment purpose | implemented | [`attachment_directive.py`](../../../services/core-control-plane/src/fdai/core/conversation/attachment_directive.py), [`test_attachment_directive.py`](../../../services/core-control-plane/tests/core/conversation/test_attachment_directive.py) | Exact leading directives select handover intent; prose and filenames do not. |
| Channel ingestion gateway seam | implemented | [`channel_gateway.py`](../../../services/core-control-plane/src/fdai/core/conversation/channel_gateway.py), [`test_channel_gateway.py`](../../../services/core-control-plane/tests/conversation/test_channel_gateway.py) | The gateway accepts an injected ingestor and fails closed when one is absent. It is not a concrete protected-ingestion implementation. |
| Slack metadata and private download | not-started | This document's Slack contracts | No signed Slack inbound adapter, private-file fetcher, production binding, or focused fetch security test is present. |
| Teams metadata and private download | not-started | This document's Teams contracts | No authenticated Teams inbound adapter, endpoint resolver, private-file fetcher, production binding, or focused fetch security test is present. |
| Protected channel ingestion composition | not-started | This document's protected-ingestion contract | No concrete ingestor currently connects channel bytes to scanning, extraction, indexing, and citations. |
| Web chat document references | in-progress | [`document_refs.py`](../../../services/operator-service/src/fdai_operator_service/families/conversation/document_refs.py), [`test_conversation_document_refs.py`](../../../services/operator-service/tests/test_conversation_document_refs.py) | Bounded parsing, the eight-reference cap, uniqueness, canonical hyphenated UUID syntax, principal-scoped resolution, uniform denial, missing-resolver 501, contained resolver failure, and order/canonical-form integrity checks are implemented and focused-tested. The versioned semantic envelope and production resolver composition do not yet carry resolved citations. |
| Web chat inline vision path | in-progress | [`composer-attachments.view.tsx`](../../../console/src/deck/composer-attachments.view.tsx), [`backend-context.ts`](../../../console/src/deck/backend-context.ts), [`conversation_images.py`](../../../services/core-control-plane/src/fdai/delivery/conversation_images.py), [`postgres_conversation_images.py`](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_conversation_images.py) | Console capture, request serialization, bounded image repositories, migrations, and historical rendering exist. The Operator semantic envelope and local narrator currently discard image attachments, and production does not bind the image repository to chat routes. |
| Document image OCR | implemented | [`processing.py`](../../../services/document-processing-worker/src/fdai_document_worker_service/adapters/processing.py), [`production.py`](../../../services/document-processing-worker/src/fdai_document_worker_service/production.py), [`test_ingestion_adapter_readiness.py`](../../../services/document-processing-worker/tests/test_ingestion_adapter_readiness.py) | The document worker binds bounded Document Intelligence `prebuilt-read` when an OCR endpoint is configured and otherwise fails closed. This does not complete channel or inline-chat ingestion. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Reconciled the design with current contracts, adapters, composition, Console code, and tests without reconstructing earlier provenance. | Current source and focused checks listed in the scope table. | Vendor adapters, protected ingestion, web document resolution, the server inline-image path, and governed runtime receipts remain open. |
| 2026-08-16 | in-progress | Added the bounded `document_refs` request contract and its principal-scoped, fail-closed resolution boundary ahead of semantic processing. | `pytest services/operator-service/tests/test_conversation_document_refs.py` passed 12 focused tests covering syntax and non-canonical UUID rejection, the eight-reference cap, uniqueness, uniform denial, missing-resolver 501, contained resolver failure, and reordered or substituted citation refusal. | Carry resolved citations into the versioned semantic envelope and bind a production resolver over PostgreSQL document metadata. |

### Remaining work

- [ ] Implement and bind signed Slack and authenticated Teams inbound adapters that retain only
  bounded opaque attachment metadata.
- [ ] Implement private vendor fetchers with server-owned endpoint resolution, credential scoping,
  redirect refusal, host allowlists, and streamed byte limits.
- [ ] Compose a concrete channel ingestor through malware, protection, extraction, indexing,
  authorization, citation, and handover paths.
- [x] Add the bounded `document_refs` request contract to the Operator conversation family and
  resolve it through principal-scoped document authorization before semantic processing.
- [ ] Carry resolved `document_refs` citations into the versioned semantic envelope, bind a
  production resolver over authoritative PostgreSQL document metadata, and add route-level tests.
- [ ] Complete the server inline-image parser, byte and media validation, repository binding,
  semantic transport, vision narrator input, history metadata, and authenticated retrieval path.
- [ ] Capture governed runtime receipts before marking any end-to-end attachment path validated.
