#!/usr/bin/env bash
# Store the GitHub runner credential on the Container Apps Job secret.
#
# Usage: set-credential.sh RESOURCE_GROUP JOB_NAME
# Run it yourself in a terminal. The value is read without echo, written only to a 0600
# temporary file that is deleted on exit, and never appears in arguments, logs, or Terraform.
#
# Create a fine-grained personal access token first, limited to this one repository, with
# Administration: read/write (runner registration), Actions: read (queue length), and
# Metadata: read. Choose the shortest expiry you can rotate, then rerun this script to rotate.
set -euo pipefail

resource_group="${1:?resource group is required}"
job_name="${2:?job name is required}"
[[ "$resource_group" =~ ^[A-Za-z0-9._()-]{1,90}$ ]] || { echo "invalid resource group" >&2; exit 1; }
[[ "$job_name" =~ ^[a-z0-9-]{2,32}$ ]] || { echo "invalid job name" >&2; exit 1; }
[[ -t 0 ]] || { echo "run this script from an interactive terminal" >&2; exit 1; }

subscription="$(az account show --query id -o tsv)"
body="$(mktemp)"
trap 'rm -f "$body"' EXIT
chmod 0600 "$body"

read -rsp "GitHub fine-grained token: " credential
echo
[[ -n "$credential" ]] || { echo "empty credential" >&2; exit 1; }
python3 -c '
import json, sys
secret = sys.stdin.read().strip()
print(json.dumps({"properties": {"configuration": {"secrets": [
    {"name": "github-runner-credential", "value": secret}]}}}))
' <<<"$credential" >"$body"
unset credential

az rest --method patch \
  --url "https://management.azure.com/subscriptions/${subscription}/resourceGroups/${resource_group}/providers/Microsoft.App/jobs/${job_name}?api-version=2024-03-01" \
  --body "@${body}" --query "properties.provisioningState" -o tsv
echo "credential stored; queued jobs carrying the runner labels now scale this job"
