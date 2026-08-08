# Compliance Catalogs

This directory stores versioned compliance frameworks and implementation crosswalks. Compliance
data maps external control identifiers to FDAI rules, Best Practices, policy profiles, and manual
evidence without turning the external framework into execution authority.

## Microsoft Cloud Security Benchmark

[`mcsb/`](mcsb/) contains version-specific `controls.yaml` and `crosswalk.yaml` pairs. A version
may be complete, partial, manual, unmapped, or metadata-only according to its declared coverage.
Preview material remains explicitly versioned and cannot silently replace an active benchmark.

The loader in
[`mcsb_catalog.py`](../../services/core-control-plane/src/fdai/rule_catalog/schema/mcsb_catalog.py)
validates benchmark versions, source documents, unique controls, coverage semantics, and references
to rules, Best Practices, and policy profiles. Collected source text and deployment evidence do not
belong in this directory.
