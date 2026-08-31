#!/usr/bin/env bash
# Compatibility shim for the removed Terraform-stream Genesis prototype.

set -euo pipefail

cat >&2 <<'EOF'
genesis-up: the Terraform-stream prototype is retired because it cannot prove
subscription readiness or resume an approved exact plan.

Use the canonical deployment CLI instead:
  uv run --project packages/deployment-cli fdaictl provision inspect --profile <profile>
  uv run --project packages/deployment-cli fdaictl onboard guided --simulate ...

Live onboarding remains unavailable until the protected foundation and
application orchestration path is complete. No Azure change was attempted.
EOF
exit 2
