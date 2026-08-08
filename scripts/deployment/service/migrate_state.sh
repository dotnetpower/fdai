#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: migrate_state.sh SERVICE ENVIRONMENT SOURCE_ROOT DESTINATION_ROOT BACKUP_DIR [--execute]" >&2
  exit 2
}

[[ $# -eq 5 || ( $# -eq 6 && "$6" == "--execute" ) ]] || usage
service="$1"
environment="$2"
source_root="$3"
destination_root="$4"
backup_dir="$5"
execute="${6:-}"
script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[[ ! -e "$backup_dir" ]] || {
  echo "backup directory already exists: $backup_dir" >&2
  exit 1
}
mkdir -m 700 "$backup_dir"
readarray -t coordinates < <(
  python3 "$script_root/state_migration.py" coordinates \
    --service "$service" \
    --environment "$environment"
)
[[ ${#coordinates[@]} -eq 4 ]] || {
  echo "state migration coordinates are incomplete" >&2
  exit 1
}
source_address="${coordinates[2]}"
destination_address="${coordinates[3]}"
source_backup="$backup_dir/source-before.tfstate"
destination_backup="$backup_dir/destination-before.tfstate"
source_work="$backup_dir/source-after.tfstate"
destination_work="$backup_dir/destination-after.tfstate"
source_view="$backup_dir/source-after.json"
destination_view="$backup_dir/destination-after.json"

terraform -chdir="$source_root" state pull >"$source_backup"
terraform -chdir="$destination_root" state pull >"$destination_backup"
chmod 600 "$source_backup" "$destination_backup"
cp "$source_backup" "$source_work"
cp "$destination_backup" "$destination_work"
terraform show -json "$source_work" >"$source_view"
terraform show -json "$destination_work" >"$destination_view"

python3 "$script_root/state_migration.py" verify \
  --source-state "$source_view" \
  --destination-state "$destination_view" \
  --source-address "$source_address" \
  --destination-address "$destination_address" \
  --phase pre

if terraform state list -state="$destination_work" | grep -Fxq "$destination_address"; then
  echo "state is already cut over; no migration was performed"
  exit 0
fi

terraform state mv \
  -state="$source_work" \
  -state-out="$destination_work" \
  "$source_address" \
  "$destination_address"
terraform show -json "$source_work" >"$source_view"
terraform show -json "$destination_work" >"$destination_view"
python3 "$script_root/state_migration.py" verify \
  --source-state "$source_view" \
  --destination-state "$destination_view" \
  --source-address "$source_address" \
  --destination-address "$destination_address" \
  --phase post

[[ "$execute" == "--execute" ]] || {
  echo "dry run complete; state backups and migrated candidates are in $backup_dir"
  exit 0
}

terraform -chdir="$destination_root" state push "$destination_work"
terraform -chdir="$source_root" state push "$source_work"
terraform -chdir="$source_root" state pull >"$backup_dir/source-verified.tfstate"
terraform -chdir="$destination_root" state pull >"$backup_dir/destination-verified.tfstate"
terraform show -json "$backup_dir/source-verified.tfstate" >"$backup_dir/source-verified.json"
terraform show -json "$backup_dir/destination-verified.tfstate" >"$backup_dir/destination-verified.json"
python3 "$script_root/state_migration.py" verify \
  --source-state "$backup_dir/source-verified.json" \
  --destination-state "$backup_dir/destination-verified.json" \
  --source-address "$source_address" \
  --destination-address "$destination_address" \
  --phase post
