#!/usr/bin/env bash
#
# resign-if-surface-staged.sh - auto re-sign the framework-surface integrity
# manifest at commit time, but ONLY when this repo is the upstream signer.
#
# Called by .githooks/pre-commit before the pre-commit framework snapshots the
# index. It is a deliberate no-op unless ALL of these hold:
#
#   1. the upstream Ed25519 PRIVATE signing key is available
#      (secrets/integrity-signing-key.pem or $FDAI_INTEGRITY_KEY), AND
#   2. a STAGED change touches the framework surface
#      (scripts/lib/framework-surface.txt).
#
# When both hold it signs the staged Git index into temporary artifacts and writes
# those blobs directly back to the index. The worktree manifest and signature are
# never modified, so concurrent unstaged integrity updates remain untouched.
#
# Fork safety: a fork never has the private key, so this always no-ops there -
# a fork still cannot mint a manifest that verifies against the committed public
# key, and its surface edits are still caught by check-integ.sh in fork mode on
# push. Automating the signature does NOT weaken the fork-facing tamper-evidence.
#
# sign-integrity.sh normally hashes the working tree. This hook selects its
# index source instead, so a partially staged framework file attests exactly
# the staged content rather than blocking or widening the commit.
# Set FDAI_SKIP_RESIGN=1 to bypass deliberately.
#
# Exit codes: 0 = no-op or re-signed OK; 1 = signing failed (blocks the commit).

set -uo pipefail

[ "${FDAI_SKIP_RESIGN:-0}" = "1" ] && exit 0

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root" || exit 1

# 1. Upstream signer only: no private key -> not us -> nothing to do.
privkey="${FDAI_INTEGRITY_KEY:-secrets/integrity-signing-key.pem}"
[ -f "$privkey" ] || exit 0

# 2. Any staged framework-surface file?
mapfile -t staged < <(git diff --cached --name-only --diff-filter=ACMRD 2>/dev/null || true)
[ "${#staged[@]}" -eq 0 ] && exit 0

surface_list="scripts/lib/framework-surface.txt"
[ -f "$surface_list" ] || exit 0

prefixes=()
exacts=()
while IFS= read -r line; do
  line="${line%%#*}"
  line="$(printf '%s' "$line" | tr -d '[:space:]')"
  [ -n "$line" ] || continue
  case "$line" in
    */) prefixes+=("$line") ;;
    *) exacts+=("$line") ;;
  esac
done < "$surface_list"

surface_staged=()
for f in "${staged[@]}"; do
  surface_touched=0
  for e in "${exacts[@]}"; do
    [ "$f" = "$e" ] && surface_touched=1 && break
  done
  if [ "$surface_touched" = 0 ]; then
    for p in "${prefixes[@]}"; do
      case "$f" in "$p"*) surface_touched=1 ; break ;; esac
    done
  fi
  [ "$surface_touched" = 1 ] && surface_staged+=("$f")
done
[ "${#surface_staged[@]}" -gt 0 ] || exit 0

# 3. Re-sign the staged snapshot without touching worktree artifacts.
echo "resign-integrity: framework surface staged -> signing index snapshot..."
temp_dir="$(mktemp -d)"
out="$temp_dir/signing.log"
manifest_out="$temp_dir/manifest.json"
signature_out="$temp_dir/manifest.json.sig"
trap 'rm -f "$out" "$manifest_out" "$signature_out"; rmdir "$temp_dir" 2>/dev/null || true' EXIT
if ! FDAI_INTEGRITY_MANIFEST_OUT="$manifest_out" \
  FDAI_INTEGRITY_SIGNATURE_OUT="$signature_out" \
  FDAI_INTEGRITY_SOURCE=index \
  bash scripts/integrity/sign-integrity.sh >"$out" 2>&1; then
  echo "resign-integrity: BLOCKED - sign-integrity failed:" >&2
  sed 's/^/  /' "$out" >&2
  exit 1
fi

# 4. Add the signed blobs to the index directly. Do not copy them into the
# worktree: pre-commit may have temporarily stashed unrelated edits there.
manifest_blob="$(git hash-object -w "$manifest_out")"
signature_blob="$(git hash-object -w "$signature_out")"
git update-index --add --cacheinfo 100644 "$manifest_blob" security/integrity/manifest.json
git update-index --add --cacheinfo 100644 "$signature_blob" security/integrity/manifest.json.sig
echo "resign-integrity: index manifest re-signed + staged; worktree preserved."
exit 0
