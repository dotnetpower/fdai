#!/usr/bin/env bash
# Pure-Rust workspace verifier (zero Python dependency).
set -euo pipefail
repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root"
cargo run --offline -p fdai-xtask -- verify
cargo run --offline -p fdai-xtask -- check-migrations
cargo run --offline -p fdai-xtask -- check-hygiene
cargo check --workspace --offline
cargo test --workspace --offline
echo "verify.sh: Pure-Rust workspace verification PASS"
