#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
database_url="postgresql+psycopg://fdai:devonly@127.0.0.1:5432/fdai"
validation_database_url="postgresql+psycopg://fdai:devonly@127.0.0.1:5433/fdai_validation"
adoption_dir="$repo_root/.fdai/service-migration-adoption"
database_recreated_marker="$repo_root/.fdai/local-database-recreated"
rollback_reference="$(git -C "$repo_root" rev-parse HEAD)"

if [[ $# -gt 1 || ( $# -eq 1 && "${1:-}" != "--dependencies-ready" && "${1:-}" != "--check" ) ]]; then
  echo "Usage: $0 [--dependencies-ready|--check]" >&2
  exit 2
fi
check_only=0
if [[ "${1:-}" == "--check" ]]; then
  check_only=1
elif [[ $# -eq 0 ]]; then
  bash "$repo_root/scripts/deployment/local/dev-up.sh"
fi

mkdir -p "$adoption_dir"
migration_order="$(
  PYTHONPATH="$repo_root/service-migrations" \
    "$repo_root/.venv/bin/python" \
    "$repo_root/service-migrations/migrate.py" \
    all order
)"
mapfile -t service_ids <<< "$migration_order"

if [[ "$check_only" == "1" ]]; then
  FDAI_DATABASE_URL="$database_url" \
    "$repo_root/.venv/bin/python" \
      "$repo_root/scripts/deployment/local/maintain-development-database.py" --check
  FDAI_DATABASE_URL="$validation_database_url" \
    "$repo_root/.venv/bin/python" -m alembic -c "$repo_root/alembic.ini" \
      current --check-heads >/dev/null
  FDAI_DATABASE_URL="$database_url" \
    "$repo_root/.venv/bin/python" -m alembic -c "$repo_root/alembic.ini" \
      current --check-heads >/dev/null
  for service_id in "${service_ids[@]}"; do
    FDAI_DATABASE_URL="$database_url" \
      "$repo_root/.venv/bin/python" -m alembic \
        -c "$repo_root/service-migrations/configs/$service_id.ini" \
        current --check-heads >/dev/null
  done
  echo "local PostgreSQL legacy schema and all five service migrations are current"
  exit 0
fi

FDAI_DATABASE_URL="$database_url" \
  "$repo_root/.venv/bin/python" \
    "$repo_root/scripts/deployment/local/maintain-development-database.py" \
      --recreated-marker "$database_recreated_marker"

if [[ -f "$database_recreated_marker" ]]; then
  "$repo_root/.venv/bin/python" \
    "$repo_root/scripts/deployment/local/reset-development-broker.py"
  rm -f "$database_recreated_marker"
fi

FDAI_DATABASE_URL="$validation_database_url" \
  "$repo_root/.venv/bin/python" -m alembic -c "$repo_root/alembic.ini" upgrade head
FDAI_DATABASE_URL="$database_url" \
  "$repo_root/.venv/bin/python" -m alembic -c "$repo_root/alembic.ini" upgrade head

for service_id in "${service_ids[@]}"; do
  evidence="$adoption_dir/$service_id.json"
  schema_evidence="$adoption_dir/$service_id-schema.json"
  migration_command=(
    "$repo_root/.venv/bin/python"
    "$repo_root/service-migrations/migrate.py"
    "$service_id"
  )

  FDAI_DATABASE_URL="$database_url" \
    PYTHONPATH="$repo_root/service-migrations" \
    "${migration_command[@]}" bootstrap \
      --evidence-output "$evidence" \
      --schema-output "$schema_evidence" \
      --rollback-reference "$rollback_reference"
done

echo "local PostgreSQL legacy schema and all five service migrations are current"
