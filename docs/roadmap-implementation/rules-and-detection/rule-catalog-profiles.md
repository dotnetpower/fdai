# Rule-catalog profiles and collectors implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Profile contract and deterministic resolution | implemented | `services/core-control-plane/src/fdai/core/rule_catalog_profiles/models.py`; `registry.py`; `services/core-control-plane/tests/core/rule_catalog_profiles/test_registry.py` | Inheritance, override precedence, cycle rejection, severity floors, and stable ordering are covered. |
| Canonical upstream profiles | implemented | `rule-catalog/profiles/baseline.yaml`; `recommended.yaml`; `strict.yaml`; `services/core-control-plane/tests/core/rule_catalog_profiles/test_full_profile_resolution.py` | All three profiles resolve against the current known Rule ids. |
| Imported compliance profiles | implemented | `rule-catalog/profiles/collected/`; `services/core-control-plane/tests/core/rule_catalog_profiles/test_full_profile_resolution.py` | Collected profiles remain reference bundles; their Rules don't gain enforcement authority from membership. |
| Runtime profile selection | implemented | `services/core-control-plane/src/fdai/runtime/rule_profile.py`; `services/core-control-plane/src/fdai/runtime/control_loop.py`; `services/core-control-plane/tests/runtime/test_rule_profile.py` | One startup resolution produces the rule tuple the T0 index carries, so the deterministic tier and the safety check read the same objects. Deployed-runtime evidence is still outstanding. |
| Reserved parser support | not-applicable | `rule-catalog/sources/*/manifest.yaml`; parser registry and focused parser-selection tests | Every approved shipped manifest selects an implemented parser. `checkov-yaml` and `gatekeeper-templates` remain explicit fail-closed placeholders until an approved source selects them; speculative parser implementation isn't part of the current scope. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | `current change`; current source, catalog, and focused tests listed in the scope table. | Wire runtime profile selection and implement only the parser plugins selected for delivery. |
| 2026-08-15 | implemented | Bound `FDAI_PROFILE_ID` at startup with one resolution, fail-closed selection and grading, and startup diagnostics that expose only the profile id, digest, and counts. | `current change`; `services/core-control-plane/src/fdai/runtime/rule_profile.py`; `services/core-control-plane/src/fdai/runtime/control_loop.py`; `pytest services/core-control-plane/tests/runtime/test_rule_profile.py` (12 passed). | Deployed-runtime evidence for a bound profile; reserved parsers stay unimplemented. |
| 2026-08-29 | not-applicable | Audited every approved shipped source manifest against the parser registry. None selects a reserved parser, so the fail-closed placeholders are the complete current behavior rather than unfinished implementation. | `current change`; source manifests, `parser.py`, and focused parser-selection checks. | Implement a reserved parser only together with a future approved source manifest. |
| 2026-08-29 | implemented | Corrected the collected-profile provenance claim: the 265 profiles are reviewed static imports, while the initiative-intent helper is offline and unregistered. Added an executable manifest-to-parser selection check. | `current change`; `azure_policy_initiative.py`; `test_parse.py`; focused parser and profile checks. | A future automated initiative refresh requires an approved source and GUID-to-Rule compiler. |
| 2026-08-29 | implemented | Hardening rounds 17-20 verified profile resolution, runtime binding, parser selection, and historical provenance. After correcting the unreachable initiative-helper claim, final review found no issue above Low. | `current change`; focused profile and parser checks passed 58 cases. | Deployed runtime evidence remains operational validation. |
| 2026-08-29 | not-applicable | Confirmed that no approved shipped source selects a reserved parser, so fail-closed placeholders are the complete current behavior. | `current change`; source manifests, parser registry, and focused selection checks. | Reopen only with a future approved source manifest. |
| 2026-08-29 | implemented | Corrected the 265 collected profiles to reviewed static imports and made the offline initiative-intent helper's unregistered status explicit. | `current change`; `azure_policy_initiative.py`; executable manifest-to-parser selection and profile checks. | Automated initiative refresh requires a future approved source and compiler. |
| 2026-08-29 | implemented | Hardening rounds 17-20 ended with no profile implementation finding above Low after correcting provenance and parser reachability claims. | `current change`; 58 focused profile and parser checks. | Deployed runtime evidence remains operational validation. |
| 2026-09-29 | in-progress | Moved the authoritative ledger out of the design owner with `migrate-roadmap-implementation-ledgers.py --merge-existing`, which kept every owner and prior ledger history row, and removed the duplicated remaining-work item that the merge carried from the prior ledger. No implementation or runtime state changed. | `current change`; this ledger, `docs/roadmap/rules-and-detection/rule-catalog-profiles.md` and its Korean pair; `check-roadmap-implementation-tracking.py`, translation, and doc-link checks. | Retain the deployed-runtime profile receipt. |

### Remaining work

- [x] The startup binder reads the governed profile id once and hands the resolved rule tuple to the T0 index that the safety check also reads, proven by `services/core-control-plane/tests/runtime/test_rule_profile.py`.
- [x] Startup diagnostics expose the profile id, digest, and counts only; rule parameters contribute to the digest but never to a log record, proven by the same focused test module.
- [x] Every approved shipped source selects an implemented parser. Reserved parser names continue to
  raise `ParserNotImplementedError`; implementation begins only with a future approved source
  manifest and its focused fixtures.
- [ ] Retain a deployed-runtime receipt showing one bound profile id and digest on a pinned revision.
