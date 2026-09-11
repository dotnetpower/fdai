# Network Connectivity Matrix implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| DNS, address-policy, TCP, manifest, and redaction engine | implemented | `scripts/deployment/azure/network_connectivity.py` and `tests/integration/scripts/test_check_network_connectivity.py` | Focused tests cover endpoint parsing, profile discovery, private/public address expectations, required and optional failures, action guidance, and redaction. |
| Protected-runner connectivity gate | implemented | `.github/workflows/deploy-dev.yml` and the network-check contract tests | The workflow composes Terraform outputs with `PREFLIGHT_NETWORK_CHECKS_JSON`, blocks required failures, removes temporary inputs, and binds only the redacted report to preflight evidence. |
| APIM route policy contract | implemented | `infra/modules/llm/apim-ai-gateway/policy.xml.tftpl`; `tests/integration/infra/test_apim_ai_gateway.py`; focused checks (`5 passed`) | Static policy checks require caller and backend Entra authentication, one PTU-to-Standard retry only on HTTP 429, and all three FDAI route-evidence headers. This is not actual-subnet or deployed response evidence. |
| DNS, protocol, port, and failure reference matrix | not-applicable | The tables in this document and linked Azure references | This is design and operator reference material; source presence does not prove a deployed route. |
| Runtime-subnet, deployed APIM, AMPLS, and operator-path evidence | not-started | The validation checklist in this document | The repository retains no complete environment-neutral receipt proving every listed identity, DNS, TLS, deployed APIM-header, image-pull, and failure-injection check from the actual subnets. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-12 | implemented | Separated the passing APIM static route-policy contract from the still-open actual-subnet and deployed response evidence. | `current change`; focused APIM module checks (`5 passed`). | Retain PTU and forced-429 deployed response headers plus actual-subnet route evidence. |
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. Separated the tested endpoint checker from deployment-specific network validation. | current change; focused checker tests and protected-runner workflow evidence listed in the scope table | Retain governed subnet-level positive and negative connectivity evidence for each selected deployment profile. |

### Remaining work

- [ ] Run identity-authenticated DNS and TLS checks from the actual runtime, APIM, and deploy-host subnets and retain a redacted governed receipt for every required path.
- [x] Verify statically that the APIM policy uses PTU first, retries to Standard only once on HTTP
  429, and emits all three FDAI route-evidence headers (`5 passed`).
- [ ] From the actual APIM path, retain PTU and forced-429 responses with all three FDAI evidence
  headers and prove that a missing header fails closed.
- [ ] Deny each required dependency in an approved validation environment and retain evidence that the matching capability degrades exactly as the failure matrix specifies.
