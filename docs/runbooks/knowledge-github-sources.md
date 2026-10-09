# Connect a GitHub knowledge source

You can connect one GitHub repository as a verified, read-only knowledge source in Knowledge >
GitHub. Connecting does not authorize a code-security scan, repository writes, or searchable
document ingestion.

## Design at a glance

The Owner submits a typed connection request through the existing repository-change outbox.
Core validates repository metadata, an exact commit, and bounded README bytes through GitHub's
API before storing source provenance. The same repository identity can later receive a separate
Owner scan permission. Operator reads the durable record and never holds GitHub credentials.

## Authority review

The initial proposal reused registration, which enables scanning. That would incorrectly turn
knowledge read access into scan consent. The revised contract creates a disabled registration
for a new knowledge source. Connecting an existing registration preserves its independently
granted scan permission. Disconnecting knowledge only revokes knowledge access, not separately
granted scan permission. A source cannot silently change its repository or credential reference.

Revision checks, safe-to-retry request identity (idempotency), and atomic state plus audit protect
connection changes. Failed provider validation leaves the prior record unchanged. A queued
request is not a verified connection; use Refresh to read the applied state.

## Configure access

- **Public access:** Select anonymous public access. FDAI does not acquire a token and refuses a
  provider response identifying the repository as private.
- **Private access:** Select the deployment GitHub App reference. Configure the existing
  `FDAI_GITHUB_APP_CLIENT_ID`, `FDAI_GITHUB_APP_INSTALLATION_ID`, and
  `FDAI_GITHUB_APP_PRIVATE_KEY` through deployment-owned secret injection. Never enter keys or
  tokens in the Console. The token provider requests one repository with `contents: read` and
  `metadata: read`; a compatibility `FDAI_GITOPS_TOKEN` is not accepted for this connection.
- **Provider origin:** The adapter uses `FDAI_GITOPS_API_BASE`, or GitHub's API by default.
  Requests have a total deadline, per-request timeout, response-byte bounds, and no redirects or
  automatic retries. Rate limits, authorization failures, malformed responses, and missing
  README content produce an explicit failed request.

## Connect and reuse

1. Open Knowledge > GitHub, choose an alias, enter `owner/repository`, and select the credential
   reference. Only an authenticated Owner can submit.
2. Refresh after the queued request completes. The source lists its exact observed commit,
   README digest, observation time, and independent scan-permission state.
3. Open Code security and explicitly enable scanning for that alias if scans are desired.
   Merely connecting or viewing the source never enables or dispatches a scan.

The connector verifies the current default branch and README. It does not claim a whole-repository
inventory, continuous synchronization, indexed citations, freshness beyond the recorded observation,
or scan completion. Searchable ingestion remains subject to the existing agent-owned document
admission and indexing workflow.

## Next steps

| To learn about | Read |
|----------------|------|
| Scan permissions and evidence | [Code Security Scanning](../roadmap/operations/code-security-scanning.md) |
| Knowledge and Operator boundaries | [Console Operations](../roadmap/interfaces/console-operations.md) |
| Document admission | [Document ingestion ownership](../roadmap/interfaces/document-ingestion-agent-ownership.md) |
