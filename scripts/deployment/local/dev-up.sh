#!/usr/bin/env bash
#
# dev-up.sh - start the local development stack (pgvector + Redpanda).
#
# On first run, seeds `infra/local/.env` from `.env.example` so the compose
# file's ${POSTGRES_PASSWORD} placeholder resolves to a documented dev
# default. `.env` is git-ignored - never committed.
#
# Exits 0 only after both containers report healthy.

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
compose_dir="${repo_root}/infra/local"
cd "${compose_dir}"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "dev-up: seeded infra/local/.env from .env.example"
fi

echo "dev-up: bringing up postgres + redpanda..."
docker compose up -d --wait

echo
echo "dev-up: OK"
echo "  postgres:  localhost:5432  (user=fdai db=fdai)"
echo "  redpanda:  localhost:19092 (kafka external listener)"
echo "  admin:     localhost:9644  (redpanda admin API)"
