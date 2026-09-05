#!/usr/bin/env bash
set -euo pipefail

if [[ ! "$PROD_CORE_IMAGE" =~ @sha256:[0-9a-f]{64}$ ]]; then
  echo "PROD_CORE_IMAGE must be digest-pinned." >&2
  exit 1
fi
if [[ -z "$PROD_ALERT_EMAIL" ]]; then
  echo "production_alert_email is required." >&2
  exit 1
fi
if [[ ! "$PROD_MONTHLY_BUDGET_AMOUNT" =~ ^[1-9][0-9]*([.][0-9]+)?$ ]]; then
  echo "PROD_MONTHLY_BUDGET_AMOUNT must be positive." >&2
  exit 1
fi
python3 -c 'import json, os; value=json.loads(os.environ["PROD_BUDGET_ALERT_EMAILS_JSON"]); assert isinstance(value, list) and value and all(isinstance(item, str) and item for item in value)'
{
  echo "TF_VAR_core_image=$PROD_CORE_IMAGE"
  echo "TF_VAR_enable_resource_locks=true"
  echo "TF_VAR_kv_purge_protection_enabled=true"
  echo "TF_VAR_kv_soft_delete_retention_days=90"
  echo "TF_VAR_postgres_backup_retention_days=35"
  echo "TF_VAR_postgres_geo_redundant_backup=true"
  echo "TF_VAR_postgres_high_availability_mode=ZoneRedundant"
  echo "TF_VAR_acr_sku=Premium"
  echo "TF_VAR_enable_monitoring=true"
  echo "TF_VAR_alert_email=$PROD_ALERT_EMAIL"
  echo "TF_VAR_monthly_budget_amount=$PROD_MONTHLY_BUDGET_AMOUNT"
  echo "TF_VAR_budget_alert_emails=$PROD_BUDGET_ALERT_EMAILS_JSON"
} >> "$GITHUB_ENV"
