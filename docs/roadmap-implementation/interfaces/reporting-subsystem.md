# Reporting Subsystem implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Core contracts, registries, engine, widgets, and default formats | implemented | `services/core-control-plane/src/fdai/core/reporting/`; `services/core-control-plane/tests/core/reporting/` | Focused tests cover catalog loading, bounds, substitution, per-widget isolation, datasource contracts, widgets, formats, and hardening safeguards. |
| Declarative report catalog and schema | implemented | `rule-catalog/reports/`; `rule-catalog/reports/schema/report.schema.json`; reporting catalog tests | Reviewed YAML reports and capability metadata load through the bounded schema. |
| Operator API read routes and Console Reports view | validated | `fdai_operator_service/reporting/incident_rca_projection.py`; `docs/baselines/incident-rca-report-assurance-2026-08-15.json`; focused Operator and Console tests | Authenticated GET-only inventory, registry, audit-backed Incident RCA rendering, and Console presentation passed without mutation authority. |
| Authoritative datasource bindings and operational freshness | in-progress | Reporting datasource adapters and provenance envelope | Adapters exist, but each deployment must bind authoritative providers and retain freshness, unavailable, timeout, and partial-widget evidence. |
| Optional PDF format and RCA dossier delivery | validated | `fdai_operator_service/reporting/pdf_format.py`; Operator operations routes; `console/src/routes/reports.tsx`; `docs/baselines/incident-rca-report-assurance-2026-08-15.json`; focused Operator and Console tests | Authenticated Browser Entra verified catalog and registry agreement, the redacted envelope, and a 38809-byte PDF while preserving gaps and adding no analysis. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger and corrected the optional PDF implementation claim; earlier provenance was not reconstructed. | `current change`; current reporting core, catalog, Operator, Console, and focused checks listed in the scope table. | Retain authoritative datasource evidence and implement optional PDF delivery before advertising it. |
| 2026-08-14 | implemented | Added opt-in PDF delivery to the independent Operator Service and exposed the Console download control only when catalog and runtime registry agree. | `current change`; service-local encoder, operations route negotiation, package extra, Console control, and focused PDF, route, composition, and Console tests. | Retain authenticated inventory, render, unavailable, error-isolation, and read-only runtime receipts. |
| 2026-08-14 | implemented | Bound the built-in Incident RCA dossier to the authoritative Operator audit reader instead of requiring an unmaterialized generic operations row. | `current change`; `incident_rca_projection.py`, composition binding, 3 focused reader tests, and 65 Operator family/composition tests. | Retain the authenticated roster-to-RCA-to-report/PDF receipt. |
| 2026-08-15 | validated | Retained authenticated inventory, registry, audit-backed render, Console, PDF, and no-RCA unavailable evidence for the built-in Incident dossier. | `current change`; `docs/baselines/incident-rca-report-assurance-2026-08-15.json`; source `014974045e70e35c26e489fa238345cf70bc3ca3` has a central receipt. | Broader production datasource campaigns remain open below. |
| 2026-08-15 | implemented | Added the `check-report-format-boundary` gate so a format module must contribute exactly one `FormatEncoder`, be exported and registered or documented as opt-in, and import nothing outside `core/reporting` and shared contracts. | `current change`; `scripts/quality/architecture/check-report-format-boundary.py`; `pytest tests/integration/scripts/test_report_format_boundary.py` (5 passed); pre-commit, `verify.sh`, and CI wiring. | Production datasource and authenticated surface receipts remain open. |

### Remaining work

- [ ] Retain governed render receipts for each production datasource showing source identity, cutoff, freshness, unavailable and timeout behavior, partial-widget isolation, and no synthetic-to-live substitution.
- [ ] Retain authenticated Operator API and Console receipts for report inventory, explicit unavailable report selection, variable rejection, unknown format, render error isolation, and read-only method enforcement.
- [x] Implement an optional PDF delivery module, registry binding, package extra, authenticated GET-only control, and focused escaping, digest, pagination, unavailable-section, no-analysis, and no-network tests before advertising `pdf`.
- [x] Downstream format additions stay behind `FormatEncoder` and composition registration: `scripts/quality/architecture/check-report-format-boundary.py` parses each format module and rejects one that does not contribute exactly one encoder, is not really imported or exported by the package, is neither registered in `defaults.py` nor listed as a reviewed opt-in, uses a relative import, or names a dependency outside `core/reporting` and the shared contracts. The package stays flat and the infrastructure modules may not define an encoder, so neither a subdirectory nor `defaults.py` itself can carry an unchecked one. It runs in pre-commit, `verify.sh`, and CI.
