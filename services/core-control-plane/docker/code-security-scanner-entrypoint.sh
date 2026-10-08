#!/bin/sh
# FDAI code-security scan runner entrypoint.
#
#   fdai-scan-runner prepare SOURCE_DIR       refresh offline vulnerability databases into
#                                             $FDAI_SCAN_CACHE (the only step that uses the network)
#   fdai-scan-runner scan [ARGS...]           run `fdai-code-security scan` with every pinned
#                                             scanner bound
#   fdai-scan-runner process-requests [ARGS]  run `fdai-code-security process-scan-requests`, the
#                                             worker for Console scan requests, with the same bindings
#
# Both scan modes add the scanner bindings and the cache; all other arguments pass through, for
# example --path, --repository, --revision, --repo-alias, --work-root, --report, --record-state,
# or --max-requests.
set -eu

CACHE="${FDAI_SCAN_CACHE:-/cache}"
BIN=/opt/scanners/bin

run_with_scanners() {
  command="$1"
  shift
  exec python -m fdai.delivery.code_security_cli "$command" \
    --scanner-bin "opengrep=$BIN/opengrep" \
    --scanner-bin "gitleaks=$BIN/gitleaks" \
    --scanner-bin "osv-scanner=$BIN/osv-scanner" \
    --scanner-bin "trivy-config=$BIN/trivy" \
    --scanner-bin "trivy-vuln=$BIN/trivy" \
    --cache-dir "$CACHE" \
    "$@"
}

case "${1:-}" in
  prepare)
    source_dir="${2:?prepare needs a source directory with lockfiles}"
    mkdir -p "$CACHE"
    "$BIN/trivy" image --download-db-only --cache-dir "$CACHE" --quiet
    OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY="$CACHE" "$BIN/osv-scanner" scan source \
      --offline-vulnerabilities --download-offline-databases --recursive "$source_dir" \
      --format json > /dev/null || [ $? -eq 1 ]
    echo '{"ok": true, "prepared": "'"$CACHE"'"}'
    ;;
  scan)
    shift
    run_with_scanners scan --prove-python /usr/local/bin/python3 "$@"
    ;;
  process-requests)
    shift
    run_with_scanners process-scan-requests "$@"
    ;;
  *)
    echo "usage: fdai-scan-runner prepare SOURCE_DIR | scan [ARGS...] | process-requests [ARGS...]" >&2
    exit 2
    ;;
esac
