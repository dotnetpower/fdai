#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
terraform_dir="${1:-$repo_root/infra}"
evidence_dir="${2:-${RUNNER_TEMP:-$repo_root/.fdai}/integrated-service-migration-adoption}"
rollback_revision="${3:-$(git -C "$repo_root" rev-parse HEAD)}"
migration_budget="${FDAI_MIGRATION_BUDGET_SECONDS:-1200}"
migration_deadline=$((SECONDS + migration_budget))

if [[ ! "$migration_budget" =~ ^[1-9][0-9]*$ ]]; then
  echo "FDAI_MIGRATION_BUDGET_SECONDS must be a positive integer" >&2
  exit 2
fi
if [[ ! "$rollback_revision" =~ ^[0-9a-f]{40}$ ]]; then
  echo "rollback revision must be a lowercase 40-character git SHA" >&2
  exit 2
fi

run_migration() {
  local remaining=$((migration_deadline - SECONDS))
  if ((remaining <= 0)); then
    echo "schema migration exceeded its ${migration_budget}s stage deadline" >&2
    return 124
  fi
  set +e
  timeout --kill-after=30s "${remaining}s" "$@"
  local status=$?
  set -e
  if [[ $status -eq 124 || $status -eq 137 ]]; then
    echo "schema migration exceeded its ${migration_budget}s stage deadline" >&2
  fi
  return "$status"
}

vault_uri="$(terraform -chdir="$terraform_dir" output -raw key_vault_uri)"
vault_name="$(VAULT_URI="$vault_uri" python3 - <<'PY'
import os
import re
from urllib.parse import urlparse

parsed = urlparse(os.environ["VAULT_URI"])
match = re.fullmatch(r"([a-z0-9-]{3,24})[.]vault[.]azure[.]net", parsed.hostname or "")
if parsed.scheme != "https" or match is None:
    raise SystemExit("Terraform key_vault_uri is not an Azure Key Vault HTTPS URI")
print(match.group(1))
PY
)"
migration_secret_name="$(REPO_ROOT="$repo_root" python3 - <<'PY'
import json
import os
from pathlib import Path

matrix = Path(os.environ["REPO_ROOT"]) / "scripts/deployment/service/service-matrix.json"
with matrix.open(encoding="utf-8") as stream:
    services = json.load(stream)["services"]
names = {item["migration_dsn_secret_name"] for item in services.values()}
if len(names) != 1:
    raise SystemExit("integrated bootstrap requires one shared migration DSN secret")
print(names.pop())
PY
)"

migration_dsn=""
for attempt in 1 2 3 4 5 6; do
  migration_dsn="$(timeout 60s az keyvault secret show \
    --vault-name "$vault_name" \
    --name "$migration_secret_name" \
    --query value \
    --only-show-errors \
    --output tsv 2>/dev/null || true)"
  [[ -n "$migration_dsn" ]] && break
  sleep "$((attempt * 2))"
done
if [[ -z "$migration_dsn" ]]; then
  echo "service migration DSN is unavailable" >&2
  exit 1
fi
echo "::add-mask::$migration_dsn"
export FDAI_DATABASE_URL="$migration_dsn"
trap 'unset FDAI_DATABASE_URL migration_dsn' EXIT

mkdir -p "$evidence_dir"
cd "$repo_root"
run_migration uv run --frozen --extra dev alembic upgrade head
migration_order_output="$(
  run_migration uv run --frozen --extra dev python \
    service-migrations/migrate.py all order
)"
mapfile -t migration_services <<< "$migration_order_output"
for service in "${migration_services[@]}"; do
  run_migration "service-migrations/bin/$service" bootstrap \
    --evidence-output "$evidence_dir/$service.json" \
    --schema-output "$evidence_dir/$service-schema.json" \
    --rollback-reference \
      "git:${rollback_revision}:service-migrations/branches/${service}/adoption.json#rollback"
done
