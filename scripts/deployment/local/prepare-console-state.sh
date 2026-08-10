#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
database_url="postgresql+psycopg://fdai:devonly@127.0.0.1:5432/fdai"

bash "$repo_root/scripts/deployment/local/dev-up.sh"
FDAI_DATABASE_URL="$database_url" \
  "$repo_root/.venv/bin/python" -m alembic -c "$repo_root/alembic.ini" upgrade head
FDAI_DATABASE_URL="$database_url" \
  "$repo_root/.venv/bin/python" \
  "$repo_root/scripts/deployment/local/prepare-operator-database-role.py"

echo "local PostgreSQL schema and Operator Service role are current"
