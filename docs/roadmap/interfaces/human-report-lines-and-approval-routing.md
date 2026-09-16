---
title: Human Report Lines and Approval Routing
---
# Human Report Lines and Approval Routing

This document defines how FDAI derives a reviewable human reporting graph from governed
organization documents and uses that graph to find eligible approvers for selected high-risk
actions. A reporting relationship can nominate a person for review, but it never grants an FDAI
role, approval capability, or execution authority.

> **Scope:** This design covers document-derived person-to-person reporting relationships,
> relationship confirmation, independent Owner review, requester consent to contact an approver,
> and human-in-the-loop (HIL) routing. Agent stewardship, RBAC, ActionType policy, and execution
> remain independent authorities.
>
> **Rollout:** New report-line behavior starts in shadow mode. A deployment must gather current
> identity, routing, response, and false-match evidence before using it to deliver live approval
> requests.

## Design at a glance

An operator explicitly imports an organization chart. FDAI extracts grounded reporting-edge
candidates, resolves both people to exact directory identities, compares the candidates with
current directory and retained graph evidence, and asks an affected person to confirm each edge.
An independent Owner reviews the confirmed edge before it enters the current reporting graph.

When an ActionType requires report-line approval, FDAI explains that requirement to the requester
and asks for consent to contact the route. After consent, it walks the current graph from the
requester to the nearest eligible ancestor. The existing ActionType and RBAC policies decide
whether that person may approve. A missing, stale, conflicting, or ineligible route produces a
held or no-op outcome.

## Independent authority axes

The implementation keeps these records separate:

| Axis | Question it answers | Authority it does not grant |
|------|---------------------|-----------------------------|
| Agent stewardship | Who is accountable for an FDAI agent's operational domain? | Human approval, RBAC, or execution |
| Human report line | Who currently reports to whom? | FDAI role or approval capability |
| RBAC and ActionType policy | Who may approve this exact action and scope? | A reporting relationship |
| Requester contact consent | May FDAI send this exact approval request to the resolved route? | Approval of the action |
| HIL decision | Did an eligible human approve this exact immutable action? | Broader or future action approval |

A person can participate in several axes, but evidence from one axis cannot satisfy another.

## Confirmed design decisions

- **Edge-level review:** Each `subject -> manager` edge has its own digest, status, evidence, and
  decision. The Console can submit a batch, but the server records one result per edge.
- **Two-stage activation:** One relationship endpoint confirms the edge, then a distinct current
  Owner approves it. The uploader, confirmer, and Owner remain attributable.
- **Conflict hold:** An uploaded edge that conflicts with directory manager evidence or an active
  graph revision stays held. Neither source wins automatically.
- **Nearest eligible ancestor:** Approval routing starts at the direct manager and walks upward.
  A manager must still satisfy the current ActionType, scope, role, quorum, and separation policy.
- **Fail closed:** If the graph cannot provide enough eligible approvers, the action does not run.
  A configured governance audience can be notified to repair coverage, but notification is not
  approval. An invalid, cyclic, or depth-bounded path is reported through the same audited
  route-unavailable outcome rather than escaping the control loop.
- **Primary-manager scope:** The initial implementation uses one active `primary_manager` edge per
  subject and effective instant. Advisory, dotted-line, mentoring, and project relationships do
  not participate in approval routing.

## Governed organization-document intake

Report-line extraction begins only after an operator selects the explicit
`report_line_bootstrap` purpose. FDAI never infers this purpose from a filename, attachment text,
or an ordinary knowledge upload.

The existing document pipeline owns upload authentication, byte limits, malware and protection
checks, format validation, optical character recognition (OCR), immutable versions, access
descriptors, retention, and audit. The report-line consumer receives only an admitted
`DocumentEnvelope`.

### Extraction order

1. Parse explicit structured rows such as `subject`, `manager`, and optional effective dates.
2. Parse bounded tables and hierarchical structural units while preserving locators.
3. Ask an injected grounded interpreter only when deterministic extraction cannot resolve a
   relationship.
4. Require a source citation for every proposed edge.
5. Resolve each endpoint to one exact active human directory identity.
6. Hold ambiguous, incomplete, low-confidence, or ungrounded proposals for review.

The upstream default interpreter abstains. A deployment can bind a provider, but model output is
always a proposal and cannot activate an edge. The worker does not invoke that interpreter when
deterministic extraction already produced at least one grounded edge.

The current source implementation recognizes exact `subject`/`employee` plus
`manager`/`reports_to` rows and supported DOCX, PPTX, and XLSX table cells. A visual chart whose
connectors cannot be recovered from structural units stays held unless a deployment supplies a
grounded interpreter. This boundary avoids turning layout guesses into organization facts.

## Reporting-edge lifecycle

Each import is immutable and safe to retry. Its edges advance independently:

```text
extracted
  -> identity_pending
  -> pending_confirmation
  -> pending_owner_review
  -> activation_pending
  -> active
```

An edge can instead become `unresolved`, `conflict`, `rejected`, `expired`, or `superseded`.

`activation_pending` records the Owner decision before the graph write. Endpoint decisions are
closed at that point. A retry can finish graph activation after interruption, while an edge never
becomes routable before both human decisions are durably fixed. A read-only structural precheck
leaves deterministic conflicts in Owner review, and a conflict won by a concurrent graph update
moves the frozen case to `conflict` instead of leaving it stuck.

An active edge records:

- exact subject and manager principal references;
- relationship kind and optional scope;
- effective and recorded times;
- source document, version, digest, and citations;
- extraction method and confidence;
- one endpoint confirmation receipt;
- one independent Owner review receipt;
- immutable graph revision and predecessor reference.

The initial lifecycle limits both an edge's validity duration and a scheduled future start to 366
days. The default validity remains 90 days, so an uploader cannot bypass periodic review with an
unbounded effective window.

An explicit rejection by either endpoint moves the edge to `conflict`, even if the other endpoint
previously confirmed it. Resolving the conflict creates a new candidate and does not rewrite the
old evidence. Exact endpoint-confirmation and Owner-review command replays return the recorded
transition, including recovery after a state write completed before its transport result.

## Graph validation and freshness

A current graph revision is accepted only when it has:

- no self-loop or directed cycle;
- at most one active primary manager for a subject at an effective instant;
- exact active human identities for both endpoints;
- a confirmation principal that is one of those exact endpoints, including on every stored-state
  read;
- no overlapping unsuperseded edge for the same subject;
- bounded traversal depth;
- a complete confirmation and Owner-review chain;
- unexpired source and directory evidence.

Whole-graph cycle detection is independent of the number of edges. The bounded traversal depth
applies when resolving one requester's approval path, not as an organization-size limit.
Activation validates historical effective-time boundaries before the aggregate compare-and-set.
Approval reads verify the stored case-set digest and build only the requested current snapshot;
they do not replay quadratic history validation on the async hot path.

Changing or expiring an edge creates a new whole-graph revision for audit. Pending approval
requests retain a separate path revision over every traversed edge and eligible rung. A change on
that path causes a fresh route decision; an unrelated edge elsewhere in the organization does not
invalidate the request.

## Relationship confirmation

Both endpoints can receive a confirmation request. One affirmative endpoint decision is sufficient
to enter Owner review, but any explicit endpoint rejection holds the edge as a conflict.

The independent Owner:

- is distinct from the recorded confirmer;
- holds the current Owner role;
- reviews the exact edge digest and source revision;
- cannot replace missing endpoint confirmation;
- cannot use approval of the graph as approval of an operational action.

Batch commands contain individual edge ids, expected revisions, and digests. One stale or invalid
edge does not change the result of another edge in the same batch.

## Approval-request consent

Report-line routing adds a consent state before a HIL item is sent:

```text
approval_required
  -> awaiting_contact_consent
  -> consented
  -> approval_pending
```

The consent record binds the requester, exact Action digest, target scope, path revision, and a
short expiry. It authorizes notification only. A changed action, target, routed edge, eligible rung,
or expired consent requires a new explanation and consent.

Decline, timeout, or an unavailable route produces a no-op with an audit record. A generic
affirmative message cannot approve a different pending request; the response must bind the
server-issued consent id. The Operator derives the command timestamp from the immutable consent
request, so an HTTP retry with the same idempotency key produces the same durable command.
Both approval-expiry and non-response workers terminalize an unanswered contact request at the
shorter consent deadline. A late answer also records the same timeout no-op instead of leaving a
permanent parked request. This undispatched lifecycle timeout is labeled `lifecycle`, not
`shadow` or `enforce`, because it grants no autonomy and never reaches an executor.
If expiry races with a valid response, the response returns the already-recorded terminal expiry
instead of surfacing an internal error or dispatching a notification.

## Eligible-ancestor routing

The approval planner continues to derive the required role and quorum from the ActionType. The
report-line resolver then:

1. starts with the requester's current direct manager;
2. validates every traversed edge against the pinned current graph revision;
3. excludes the requester, action target person, executor, and prior approvers;
4. rechecks active identity and ActionType-plus-scope approval policy;
5. selects the nearest eligible distinct principals until quorum is met;
6. records the path and eligibility evidence digest in the parked approval.

Successful approval-claim and terminal execution audits carry the route digest, path revision, and
whole-graph revision observed for that decision.

If the route cannot satisfy quorum, FDAI does not silently widen to an arbitrary Owner or group.
Only an explicit ActionType route policy can select a separate fallback. Existing channel fallback
continues to handle delivery failures, while the non-response supervisor advances only through
the approved eligible route.

Eligibility, graph revision, consent expiry, action integrity, and no-self-approval are rechecked
when a decision arrives and immediately before dispatch.

The report-line policy and runtime accept quorum `1` only. Higher-quorum ActionTypes remain on
their existing workflow or human-access approval path until a separately reviewed multi-slot
report-line contract is implemented; unsupported quorum values fail during configuration.

## Configuration

The default is disabled. A deployment configures all of these inputs before report-line routing is
available:

| Setting | Purpose |
|---------|---------|
| `FDAI_GRAPH_REPORT_LINES_ENABLED` | Enables read-only Microsoft Graph user and manager lookup in the document worker. |
| `FDAI_REPORT_LINE_CONFIDENCE_FLOOR` | Sets the candidate confidence floor without granting activation. |
| `FDAI_REPORT_LINE_APPROVAL_ROUTES_JSON` | Selects exact ActionTypes with current quorum `1`; an empty value preserves existing approval routes. |
| `FDAI_PANTHEON_APPROVER_ACTIONS_JSON` | Lists the exact ActionTypes each normalized human principal may approve. |
| `FDAI_REPORT_LINE_APPROVER_SCOPES_JSON` | Lists the exact target scopes each principal may approve for each selected ActionType. |

The current Graph adapter uses the existing worker managed identity and `User.Read.All`. No
directory writer or executor credential is added.

## API surfaces

| Method and path | Purpose |
|-----------------|---------|
| `GET /ingestion/uploads/{upload_id}/report-line-draft` | Read the authorized grounded extraction artifact. |
| `GET /handover/reporting-lines` | Read the current principal-filtered graph and review state. |
| `GET/POST /handover/reporting-line-cases...` | Create, inspect, confirm, or independently review immutable edge cases. |
| `GET /hil/report-line-contact-requests` | List contact-consent requests owned by the authenticated requester. |
| `POST /hil/{approval_id}/report-line-contact` | Record consent or cancellation without approving the action. |

## Agent and service ownership

No new agent is introduced:

| Stage | Owner |
|-------|-------|
| Document ingress | Huginn |
| Source and graph validation | Forseti |
| Endpoint confirmation and independent Owner approval | Var |
| Immutable relationship and route audit | Saga |
| Current graph projection | Muninn |
| Operational action execution | Thor |
| Effect verification and recovery | Heimdall and Vidar through their existing boundaries |

The Operator Service authenticates people, renders projections, and publishes typed commands. It
does not activate graph edges, decide approval eligibility, or execute an action. The document
worker extracts candidates but cannot approve them.

## Privacy and retention

Organization documents and reporting relationships are sensitive identity data:

- general event topics and logs carry stable references and digests, not names or document text;
- a person can read edges where they are an endpoint, while Owners can review the bounded graph;
- Console decoders reject any report-line or contact projection that claims approval or execution
  authority;
- source citations remain subject to the document access descriptor;
- deployment policy owns retention duration and legal hold;
- superseded edges remain audit evidence but are unavailable for routing;
- upstream code, examples, and tests use synthetic identities only.

## Console experience

`Governance > Agent oversight > Reporting lines` shows:

- import state and source freshness;
- extracted edges with citations and identity-resolution state;
- endpoint confirmation and Owner-review state;
- conflicts against directory or current graph evidence;
- the active graph revision and coverage gaps;
- a route preview that explains why each ancestor is eligible or skipped.

For a high-risk conversational request, FDAI shows an explicit consent card with the action summary,
impact scope, intended report-line route, expiry, and `Send approval request` or `Cancel` actions.
No notification is sent before that consent is recorded.

## Rollout and verification

Rollout proceeds in four stages:

1. extract and review candidates without activating a graph;
2. activate reviewed graph revisions but use them only for route previews;
3. compare report-line routes with existing approval routes in shadow mode;
4. promote explicitly selected ActionTypes and scopes after measured evidence.

Focused verification covers no-eligible-ancestor refusal, malformed escalation context, changed
path evidence, current role and scope policy, and approval by a later eligible rung after
non-response advancement.

Any unauthorized route, stale-edge use, identity mismatch, consent bypass, or self-approval
demotes the capability to shadow mode and holds affected actions.

## Related docs

| To learn about | Read |
|----------------|------|
| Implementation status and remaining work | [Implementation ledger](../../roadmap-implementation/interfaces/human-report-lines-and-approval-routing.md) |
| Human access and operational assignment | [Human-agent assignment and knowledge transfer](human-agent-assignment-and-knowledge-handover.md) |
| Agent accountability | [Agent operational ownership and ownership handover](agent-stewardship-and-handover.md) |
| Human roles and identity | [User RBAC and Entra identity](user-rbac-and-identity.md) |
| Approval timeout and escalation | [Escalation and standing authority](../decisioning/escalation-and-standing-authority.md) |
| Governed attachment intake | [Conversation attachments](conversation-attachments.md) |
