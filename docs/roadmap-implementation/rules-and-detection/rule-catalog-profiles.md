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
| Reserved parser support | not-applicable | `rule-catalog/sources/*/manifest.yaml`; parser registry and focused selection tests | Every approved shipped manifest selects an implemented parser. Reserved parsers remain fail-closed until a future approved manifest selects them. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | `current change`; current source, catalog, and focused tests listed in the scope table. | Wire runtime profile selection and implement only the parser plugins selected for delivery. |
| 2026-08-15 | implemented | Bound `FDAI_PROFILE_ID` at startup with one resolution, fail-closed selection and grading, and startup diagnostics that expose only the profile id, digest, and counts. | `current change`; `services/core-control-plane/src/fdai/runtime/rule_profile.py`; `services/core-control-plane/src/fdai/runtime/control_loop.py`; `pytest services/core-control-plane/tests/runtime/test_rule_profile.py` (12 passed). | Deployed-runtime evidence for a bound profile; reserved parsers stay unimplemented. |
| 2026-08-29 | not-applicable | Confirmed that no approved shipped source selects a reserved parser, so fail-closed placeholders are the complete current behavior. | `current change`; source manifests, parser registry, and focused selection checks. | Reopen only with a future approved source manifest. |
| 2026-08-29 | implemented | Corrected the 265 collected profiles to reviewed static imports and made the offline initiative-intent helper's unregistered status explicit. | `current change`; `azure_policy_initiative.py`; executable manifest-to-parser selection and profile checks. | Automated initiative refresh requires a future approved source and compiler. |

### Remaining work

- [x] The startup binder reads the governed profile id once and hands the resolved rule tuple to the T0 index that the safety check also reads, proven by `services/core-control-plane/tests/runtime/test_rule_profile.py`.
- [x] Startup diagnostics expose the profile id, digest, and counts only; rule parameters contribute to the digest but never to a log record, proven by the same focused test module.
- [ ] Retain a deployed-runtime receipt showing one bound profile id and digest on a pinned revision.
- [x] All approved shipped manifests select implemented parsers; reserved names preserve
  `ParserNotImplementedError` until a future approved source and fixtures arrive.
