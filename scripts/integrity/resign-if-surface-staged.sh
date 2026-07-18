#!/usr/bin/env bash
#
# resign-if-surface-staged.sh - auto re-sign the framework-surface integrity
# manifest at commit time, but ONLY when this repo is the upstream signer.
#
# Called from the pre-commit hook (.githooks/pre-commit and the pre-commit
# framework). It is a deliberate no-op unless ALL of these hold:
#
#   1. the upstream Ed25519 PRIVATE signing key is available
#      (secrets/integrity-signing-key.pem or $FDAI_INTEGRITY_KEY), AND
#   2. a STAGED change touches the framework surface
#      (scripts/lib/framework-surface.txt).
#
# When both hold it runs scripts/integrity/sign-integrity.sh (regenerate manifest + sign)
# and stages the refreshed manifest + signature so they land in the SAME commit
# as the surface change. This removes the manual "re-sign before release" chore
# for the maintainer.
#
# Fork safety: a fork never has the private key, so this always no-ops there -
# a fork still cannot mint a manifest that verifies against the committed public
# key, and its surface edits are still caught by check-integ.sh in fork mode on
# push. Automating the signature does NOT weaken the fork-facing tamper-evidence.
#
# sign-integrity.sh hashes the WORKING TREE. A framework-surface file that is
# both staged and modified again would therefore attest content outside the
# commit. This hook detects that partial-staging state and blocks the commit.
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

# 3. Refuse to attest working-tree content that is not in the index.
for f in "${surface_staged[@]}"; do
  if ! git diff --quiet -- "$f"; then
    echo "resign-integrity: BLOCKED - staged framework-surface file also has unstaged changes: $f" >&2
    echo "  Stage the whole file, revert the unstaged part, or set FDAI_SKIP_RESIGN=1 deliberately." >&2
    exit 1
  fi
done

# 4. Re-sign and stage the refreshed artifacts into this commit.
echo "resign-integrity: framework surface staged -> re-signing manifest..."
out="$(mktemp)"
if ! bash scripts/integrity/sign-integrity.sh >"$out" 2>&1; then
  echo "resign-integrity: BLOCKED - sign-integrity failed:" >&2
  sed 's/^/  /' "$out" >&2
  rm -f "$out"
  exit 1
fi
rm -f "$out"
git add security/integrity/manifest.json security/integrity/manifest.json.sig
echo "resign-integrity: manifest re-signed + staged."
exit 0
