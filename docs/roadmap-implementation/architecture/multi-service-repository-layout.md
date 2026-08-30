# Multi-Service Repository Layout implementation ledger

This delivery ledger tracks the physical workspace and package boundaries while the roadmap owner
remains focused on the normative repository layout.

## Implementation status

### Implementation scope
| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Five backend service distributions | implemented | Five `services/*/pyproject.toml` manifests; `config/independent-services.json`; `check-independent-services.py` (`services=5`) | Each backend service owns its source package, tests, image, process identity, and service migration branch. |
| Core cryptographic runtime dependency | implemented | `services/core-control-plane/pyproject.toml`; `uv.lock`; signed observation tests | Core alone owns the Ed25519 verification dependency. The signing seed remains a deployment secret reference and no cross-service implementation import is introduced. |
| Shared service-contract SDK | implemented | `packages/service-contracts/pyproject.toml`; `packages/service-contracts/src/fdai_service_contracts/`; independent-service gate | Versioned wire contracts are packaged separately and do not import service implementations. |
| Root workspace coordination | implemented | Root `pyproject.toml`; `uv.lock`; service-owned manifests | The root coordinates development tooling and integration; it does not publish an FDAI runtime distribution. |
| Cross-service implementation isolation | implemented | `uv run python scripts/quality/architecture/check-independent-services.py` (`top_level_source=0`, `service_forbidden=0`) | Services communicate through versioned contracts and owned persistence or event-bus surfaces rather than implementation imports. |

### Implementation history
| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-31 | implemented | Added Core-owned Ed25519 observation verification without changing the five-service distribution inventory or introducing a cross-service implementation import. | `current change`; Core manifest and lockfile; focused signed-observation tests; `check-independent-services.py` passed. | No physical package-boundary work remains for this dependency. |
| 2026-08-24 | implemented | Adopted a focused physical-layout owner after the five-service extraction and separated it from module boundaries, dependency injection, and repository conventions. Earlier decomposition provenance remains in the service-decomposition ledger and was not reconstructed here. | `current change`; five service manifests, shared SDK manifest, root workspace manifest, and `check-independent-services.py` passed with `services=5`, `top_level_source=0`, and `service_forbidden=0`. | No physical package-boundary work remains in this owner. Deployment promotion evidence remains with the service-decomposition and graduation owners. |

### Remaining work
- [x] Keep the five service distributions, shared contract SDK, root workspace-only manifest, and cross-service implementation-import prohibition pinned by `check-independent-services.py`.
