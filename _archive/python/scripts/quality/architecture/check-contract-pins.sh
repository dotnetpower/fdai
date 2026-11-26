#!/usr/bin/env bash
# Fail at commit time on the two contract drifts that otherwise stall the shared
# validation queue for every session: an unregistered composition module and a
# legacy migration head whose pins were not advanced.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

if [[ -x .venv/bin/python ]]; then
  interpreter=(.venv/bin/python)
else
  interpreter=(uv run python)
fi

PYTHONPATH=. "${interpreter[@]}" -m pytest -q --no-cov -p no:cacheprovider \
  tests/integration/test_composition_package_split.py \
  tests/integration/services/test_service_migration_inventory.py
