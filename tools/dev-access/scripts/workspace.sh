#!/usr/bin/env bash

DEV_ACCESS_WORKSPACE_PINNED=false
if [[ -n "${FDAI_DEV_ACCESS_WORKSPACE+x}" ]]; then
  dev_access_workspace="${FDAI_DEV_ACCESS_WORKSPACE}"
elif [[ -f "${ROOT_DIR}/.profiles/active-workspace" ]]; then
  dev_access_workspace="$(<"${ROOT_DIR}/.profiles/active-workspace")"
else
  return 0
fi

if [[ ! "${dev_access_workspace}" =~ ^[A-Za-z0-9_-]+$ ]]; then
  printf 'tools/dev-access/README.md:1:1: error: invalid dev-access workspace; set FDAI_DEV_ACCESS_WORKSPACE or .profiles/active-workspace to a Terraform workspace name\n' >&2
  exit 21
fi

export TF_WORKSPACE="${dev_access_workspace}"
DEV_ACCESS_WORKSPACE_PINNED=true
