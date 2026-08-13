#!/usr/bin/env bash
#
# dev-up.sh - start the local development stack (runtime/validation pgvector + Redpanda + ClamAV).
#
# On first run, seeds `infra/local/.env` from `.env.example` so the compose
# file's ${POSTGRES_PASSWORD} placeholder resolves to a documented dev
# default. `.env` is git-ignored - never committed.
#
# Exits 0 only after every container reports healthy.

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
compose_dir="${repo_root}/infra/local"
cd "${compose_dir}"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "dev-up: seeded infra/local/.env from .env.example"
fi

echo "dev-up: bringing up postgres + redpanda + clamav..."
docker compose up -d --wait

echo
echo "dev-up: OK"
echo "  postgres runtime:     localhost:5432  (user=fdai db=fdai)"
echo "  postgres validation:  localhost:5433  (user=fdai db=fdai_validation)"
echo "  redpanda:  localhost:19092 (kafka external listener)"
echo "  admin:     localhost:9644  (redpanda admin API)"
echo "  clamav:    localhost:3310  (clamd stream scanner)"
