#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
database_url="postgresql+psycopg://fdai:devonly@127.0.0.1:5432/fdai"
adoption_dir="$repo_root/.fdai/service-migration-adoption"
rollback_reference="$(git -C "$repo_root" rev-parse HEAD)"

bash "$repo_root/scripts/deployment/local/dev-up.sh"
FDAI_DATABASE_URL="$database_url" \
  "$repo_root/.venv/bin/python" -m alembic -c "$repo_root/alembic.ini" upgrade head

mkdir -p "$adoption_dir"
for service_id in core-control-plane operator-service; do
  evidence="$adoption_dir/$service_id.json"
  schema_evidence="$adoption_dir/$service_id-schema.json"
  migration_command=(
    "$repo_root/.venv/bin/python"
    "$repo_root/service-migrations/migrate.py"
    "$service_id"
  )

  FDAI_DATABASE_URL="$database_url" \
    PYTHONPATH="$repo_root/service-migrations" \
    "${migration_command[@]}" prepare-adoption \
      --evidence-output "$evidence" \
      --schema-output "$schema_evidence" \
      --rollback-reference "$rollback_reference"
  FDAI_DATABASE_URL="$database_url" \
    PYTHONPATH="$repo_root/service-migrations" \
    "${migration_command[@]}" stamp-baseline --evidence "$evidence"
  FDAI_DATABASE_URL="$database_url" \
    PYTHONPATH="$repo_root/service-migrations" \
    "${migration_command[@]}" upgrade head
done

echo "local PostgreSQL legacy schema and Core/Operator service migrations are current"
