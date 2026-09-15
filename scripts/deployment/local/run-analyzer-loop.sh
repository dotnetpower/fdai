#!/usr/bin/env bash
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
exec bash "$repo_root/scripts/deployment/local/run-console-service.sh" local-analyzer
