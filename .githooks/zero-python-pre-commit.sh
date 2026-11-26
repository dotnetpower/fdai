#!/usr/bin/env bash
set -euo pipefail
cargo run --offline -p fdai-xtask -- pre-commit
cargo test --workspace --offline
