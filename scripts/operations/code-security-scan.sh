#!/usr/bin/env bash
# Scan a local folder with FDAI's code-security scanners and write a report.
#
#   scripts/operations/code-security-scan.sh FOLDER [options]
#
# Options:
#   --include-uncommitted   scan the working files instead of the committed HEAD
#   --report-dir DIR        where report.md, report.html, and report.json go
#                           (default: $FDAI_CODE_SECURITY_HOME/reports/<folder-name>)
#   --alias NAME            repository alias shown in the report and the Console
#   --locale en|ko          report language (default: en)
#   --record-state          also record the review for the Console; reads FDAI_STATE_STORE_DSN
#                           from this environment and passes it to the container by name only
#   --prove                 also reproduce verified issues in the proof lane; uses the larger
#                           `prover` image target with Node.js, gcc, a JDK, and the .NET SDK
#   --rebuild               rebuild the scanner image first
#   --refresh-db            refresh the offline vulnerability databases first
#
# The scanner image pins every scanner by SHA-256. The first run builds the image and downloads
# the offline Trivy and OSV databases; those are the only steps that use the network. The scan
# itself runs with --network none, and every scanner runs inside bubblewrap with the folder
# mounted read-only. FDAI_CODE_SECURITY_HOME defaults to ~/.cache/fdai-code-security.
set -euo pipefail

usage() { sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; }

[[ $# -ge 1 ]] || { usage >&2; exit 2; }
case "$1" in -h|--help) usage; exit 0 ;; esac

folder="$1"
shift
[[ -d "$folder" ]] || { echo "error: $folder is not a directory" >&2; exit 2; }
folder="$(cd "$folder" && pwd -P)"

include_uncommitted=""
record_state=""
prove=""
report_dir=""
alias_name=""
locale="en"
rebuild=0
refresh_db=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --include-uncommitted) include_uncommitted="--include-uncommitted" ;;
    --record-state) record_state="--record-state" ;;
    --prove) prove="--prove" ;;
    --report-dir) report_dir="${2:?--report-dir needs a value}"; shift ;;
    --alias) alias_name="${2:?--alias needs a value}"; shift ;;
    --locale) locale="${2:?--locale needs a value}"; shift ;;
    --rebuild) rebuild=1 ;;
    --refresh-db) refresh_db=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown option $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done
case "$locale" in en|ko) ;; *) echo "error: --locale must be en or ko" >&2; exit 2 ;; esac

repo_root="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
image="${FDAI_CODE_SECURITY_IMAGE:-fdai-code-security-scanner:local}"
target="runtime"
if [[ -n "$prove" ]]; then
  image="${FDAI_CODE_SECURITY_PROVER_IMAGE:-fdai-code-security-scanner:prover}"
  target="prover"
fi
home_dir="${FDAI_CODE_SECURITY_HOME:-${XDG_CACHE_HOME:-$HOME/.cache}/fdai-code-security}"
name="$(basename "$folder" | tr -c 'A-Za-z0-9._\n-' '-' | sed 's/^[-._]*//; s/[-._]*$//' | cut -c1-64)"
name="${name:-local-folder}"
report_dir="${report_dir:-$home_dir/reports/$name}"
mkdir -p "$home_dir/cache" "$home_dir/work" "$report_dir"
chmod 700 "$home_dir" "$home_dir/work"
report_dir="$(cd "$report_dir" && pwd -P)"

if [[ $rebuild -eq 1 ]] || ! docker image inspect "$image" > /dev/null 2>&1; then
  echo "building $image ..." >&2
  docker build -f "$repo_root/services/core-control-plane/docker/code-security-scanner.Dockerfile" \
    --target "$target" -t "$image" "$repo_root" >&2
fi

user="$(id -u):$(id -g)"
if [[ $refresh_db -eq 1 ]] || [[ -z "$(ls -A "$home_dir/cache" 2> /dev/null)" ]]; then
  echo "refreshing offline vulnerability databases ..." >&2
  docker run --rm --user "$user" -e HOME=/tmp \
    -v "$folder:/source:ro" -v "$home_dir/cache:/cache" \
    "$image" prepare /source >&2
fi

network="none"
env_args=()
if [[ -n "$record_state" ]]; then
  [[ -n "${FDAI_STATE_STORE_DSN:-}" ]] || {
    echo "error: --record-state needs FDAI_STATE_STORE_DSN in the environment" >&2
    exit 2
  }
  # The state store is a loopback PostgreSQL in local development, so the container shares the
  # host network only for this option. The DSN passes by variable name, never on the command line.
  network="host"
  env_args=(-e FDAI_STATE_STORE_DSN)
fi

alias_args=()
[[ -n "$alias_name" ]] && alias_args=(--repo-alias "$alias_name")

docker run --rm --user "$user" --network "$network" -e HOME=/tmp "${env_args[@]}" \
  --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
  -v "$folder:/source/$name:ro" \
  -v "$home_dir/cache:/cache" \
  -v "$home_dir/work:/work" \
  -v "$report_dir:/report" \
  "$image" scan \
  --path "/source/$name" ${include_uncommitted:+"$include_uncommitted"} \
  "${alias_args[@]}" \
  --work-root /work \
  --report /report --report-locale "$locale" \
  ${record_state:+"$record_state"} ${prove:+"$prove"}

echo "report: $report_dir/report.html" >&2
