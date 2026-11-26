# Archived Legacy Python Sources (`_archive/python/`)

This directory holds the archived legacy Python implementation, Alembic/service migrations,
Python scripts, and pytest suites quarantined during the Pure-Rust cutover.

- **Pre-cutover Git rollback tag**: `archive/python-pre-cutover-20261127`
- **Active runtime**: 100% Pure-Rust workspace (`Cargo.toml`, `crates/`, `services_rs/`,
  `lifecycle_rs/`, `extensions_rs/`, `benchmarks_rs/`, `tools_rs/`, `console_rs/`,
  `migrations/`, `deploy_rs/`).
- **Non-Python assets preserved in active trees**:
  - `packages/network-topology-contracts/` (TypeScript)
  - `console/` & `lifecycle/{hub,release-hub}/ui/` (TypeScript/React UIs)
  - `console_rs/assets/`, `services_rs/*/assets/`, `tools_rs/fdai-deployment-cli/assets/`,
    `crates/contracts/fdai-contracts/assets/`, `extensions_rs/*/assets/`, `lifecycle_rs/*/ui/`
  - `rule-catalog/code-security/` (domain Python code-security analysis rules)
  - `.github/actions/verify-ci-runner-source/verify.py` (CI admission verifier)
