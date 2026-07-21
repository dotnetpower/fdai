#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

bash "$repo_root/scripts/deployment/local/dev-up.sh"
FDAI_DATABASE_URL="postgresql+psycopg://fdai:devonly@127.0.0.1:5432/fdai" \
  "$repo_root/.venv/bin/python" -m alembic -c "$repo_root/alembic.ini" upgrade head

echo "local PostgreSQL schema is current"
