#!/usr/bin/env bash
set -euo pipefail

action="${DOCUMENT_OCR_ACTION:-preserve}"
if terraform state list | grep -Fxq \
  'module.document_intelligence[0].azurerm_cognitive_account.document_intelligence'; then
  existing_resource=true
else
  existing_resource=false
fi
case "$action" in
  preserve)
    resource_enabled="$existing_resource"
    provider="$(terraform output -raw document_ocr_provider 2>/dev/null \
      || printf '%s' local_python)"
    ;;
  use_local_retain)
    resource_enabled="$existing_resource"
    provider=local_python
    ;;
  use_azure_provision)
    resource_enabled=true
    provider=azure_document_intelligence
    ;;
  deprovision_use_local)
    resource_enabled=false
    provider=local_python
    ;;
  *)
    echo "Document OCR action is invalid." >&2
    exit 1
    ;;
esac
printf 'TF_VAR_enable_document_intelligence=%s\n' "$resource_enabled" >> "$GITHUB_ENV"
printf 'TF_VAR_document_ocr_provider=%s\n' "$provider" >> "$GITHUB_ENV"
