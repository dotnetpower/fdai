#!/bin/sh
# FDAI code-security scan runner entrypoint.
#
#   fdai-scan-runner prepare SOURCE_DIR       refresh offline vulnerability databases into
#                                             $FDAI_SCAN_CACHE (the only step that uses the network)
#   fdai-scan-runner prepare-snapshot SOURCE_DIR ROOT
#                                           refresh in private staging, then publish an immutable
#                                           generation and atomically update ROOT/current.json
#   fdai-scan-runner prepare-source [ARGS]   acquire a source handoff with `prepare-scan`
#   fdai-scan-runner scan [ARGS...]           run `fdai-code-security scan` with every pinned
#                                             scanner bound
#   fdai-scan-runner process-requests [ARGS]  run `fdai-code-security process-scan-requests`, the
#                                             worker for Console scan requests, with the same bindings
#   fdai-scan-runner process-schedule [ARGS]  run `fdai-code-security process-scheduled-scans`, the
#                                             scheduled scan of every enabled registered repository
#   fdai-scan-runner serve-workers [ARGS]     supervise both bounded workers serially
#
# Every scan mode adds the scanner bindings and the cache; all other arguments pass through, for
# example --path, --repository, --revision, --repo-alias, --work-root, --report, --record-state,
# --prove, --max-requests, or --max-repositories. `scan` also binds each proof toolchain the image carries.
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
  prepare-snapshot)
    source_dir="${2:?prepare-snapshot needs a source directory}"
    snapshot_root="${3:?prepare-snapshot needs a snapshot root}"
    mkdir -p "$snapshot_root/staging"
    stage="$(mktemp -d "$snapshot_root/staging/cache-XXXXXXXX")"
    trap 'rm -rf "$stage"' EXIT HUP INT TERM
    FDAI_SCAN_CACHE="$stage" fdai-scan-runner prepare "$source_dir" > /dev/null
    fdai-code-security publish-cache-snapshot --path "$stage" --out "$snapshot_root"
    ;;
  prepare-source)
    shift
    exec fdai-code-security prepare-scan "$@"
    ;;
  prepare)
    source_dir="${2:?prepare needs a source directory with lockfiles}"
    mkdir -p "$CACHE"
    "$BIN/trivy" image --download-db-only --cache-dir "$CACHE" --quiet
    # osv-scanner exits 1 when it finds vulnerabilities and 128 when the folder has no lockfile.
    status=0
    OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY="$CACHE" "$BIN/osv-scanner" scan source \
      --offline-vulnerabilities --download-offline-databases --recursive "$source_dir" \
      --format json > /dev/null || status=$?
    case "$status" in 0|1|128) ;; *) exit "$status" ;; esac
    echo '{"ok": true, "prepared": "'"$CACHE"'"}'
    ;;
  scan)
    shift
    # Bind every proof toolchain the image carries; they take effect only with --prove.
    for runtime in node:node gcc:cc java:java dotnet:dotnet; do
      executable="$(command -v "${runtime%%:*}" || true)"
      if [ -n "$executable" ]; then
        set -- "$@" "--prove-${runtime#*:}" "$executable"
      fi
    done
    run_with_scanners scan --prove-python /usr/local/bin/python3 "$@"
    ;;
  process-requests)
    shift
    run_with_scanners process-scan-requests "$@"
    ;;
  process-schedule)
    shift
    run_with_scanners process-scheduled-scans "$@"
    ;;
  serve-workers)
    shift
    run_with_scanners serve-workers "$@"
    ;;
  *)
    echo "usage: fdai-scan-runner prepare SOURCE_DIR | prepare-snapshot SOURCE_DIR ROOT | prepare-source [ARGS...] | scan [ARGS...] | process-requests [ARGS...] | process-schedule [ARGS...] | serve-workers [ARGS...]" >&2
    exit 2
    ;;
esac
