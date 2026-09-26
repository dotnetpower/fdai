#!/usr/bin/env bash
#
# check-integrity.sh - OFFLINE verifier for the framework-surface manifest.
#
# Fully offline: needs only the three committed artifacts plus openssl + python3.
# No network, no OCSP, no certificate chain - the signature is self-contained.
#
#   security/integrity/manifest.json              (signed SHA-256 map)
#   security/integrity/manifest.json.sig          (Ed25519 detached signature)
#   security/integrity/upstream-signing-key.pub   (upstream public key)
#
# It performs two independent checks:
#   1. SIGNATURE - the manifest verifies against the committed public key. A
#      fork cannot forge this without the upstream private key. A failure here
#      is ALWAYS an error (a forged / corrupted / mismatched manifest).
#   2. CONTENT   - every framework-surface file on disk still hashes to the
#      value the signed manifest records, no surface file is missing, and no
#      NEW tracked file has appeared under the surface.
#
# Mode-aware result (same detection as check-protected-paths.sh):
#   * FORK mode      -> a CONTENT mismatch is a HARD FAIL (exit 1): the fork
#                       edited the framework surface it must not touch.
#   * UPSTREAM mode  -> a CONTENT mismatch is ADVISORY (exit 0): evolving the
#                       framework is legitimate; you just need to re-sign
#                       (scripts/integrity/sign-integrity.sh). A SIGNATURE failure is
#                       still a hard error in both modes.
#
# Mode detection (first match wins): FDAI_FORK=1 | .fdai-fork marker |
#   git config --bool fdai.fork == true. Otherwise UPSTREAM.
#
# Usage:  scripts/integrity/check-integrity.sh
# Exit:   0 = clean (or upstream advisory); 1 = tampered/forged; 2 = setup error.

set -uo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root"

INTEGRITY_DIR="security/integrity"
MANIFEST="$INTEGRITY_DIR/manifest.json"
SIG="$INTEGRITY_DIR/manifest.json.sig"
PUBKEY="$INTEGRITY_DIR/upstream-signing-key.pub"

command -v openssl >/dev/null 2>&1 || { echo "check-integrity: ERROR - openssl not found." >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "check-integrity: ERROR - python3 not found." >&2; exit 2; }

for f in "$MANIFEST" "$SIG" "$PUBKEY"; do
  if [ ! -f "$f" ]; then
    echo "check-integrity: ERROR - missing artifact: $f" >&2
    echo "  Upstream must generate + sign first: scripts/integrity/sign-integrity.sh --gen-key && scripts/integrity/sign-integrity.sh" >&2
    exit 2
  fi
done

# ---- mode detection --------------------------------------------------------
mode="upstream"
if [ "${FDAI_FORK:-0}" = "1" ]; then
  mode="fork"
elif [ -f "$repo_root/.fdai-fork" ]; then
  mode="fork"
elif [ "$(git config --bool fdai.fork 2>/dev/null || echo false)" = "true" ]; then
  mode="fork"
fi

# ---- 1. signature (always authoritative) -----------------------------------
# The committed signature is base64-armored (ASCII text). Decode it to raw
# bytes for openssl, in a temp file that is always cleaned up.
raw_sig="$(mktemp)"
trap 'rm -f "$raw_sig"' EXIT
if ! base64 -d "$SIG" > "$raw_sig" 2>/dev/null; then
  echo "check-integrity: ERROR - $SIG is not valid base64 (corrupt signature file)." >&2
  exit 1
fi
if openssl pkeyutl -verify -pubin -inkey "$PUBKEY" -rawin -sigfile "$raw_sig" -in "$MANIFEST" >/dev/null 2>&1; then
  echo "check-integrity: signature OK (verified offline against $PUBKEY)."
else
  {
    echo ""
    echo "=============================================================="
    echo " FAIL - manifest signature did NOT verify"
    echo "=============================================================="
    echo "  $MANIFEST does not match its signature under the committed"
    echo "  public key. The manifest was altered, corrupted, or signed"
    echo "  with a different key. This is never acceptable in any mode."
  } >&2
  exit 1
fi

# ---- 2. content (hash every surface file; detect edits/adds/deletes) -------
content_report="$(
  python3 - "$MANIFEST" <<'PY'
import hashlib, json, subprocess, sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
surface = manifest.get("surface", [])
recorded = manifest.get("files", {})


def matches(path: str) -> bool:
    for entry in surface:
        if entry.endswith("/"):
            if path.startswith(entry):
                return True
        elif path == entry:
            return True
    return False


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


mismatched, missing = [], []
for rel, want in sorted(recorded.items()):
    fp = Path(rel)
    if not fp.is_file():
        missing.append(rel)
        continue
    if sha256(fp) != want:
        mismatched.append(rel)

# Detect NEW tracked files that appeared under the surface but are not signed.
out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, text=True, check=True)
tracked = [p for p in out.stdout.split("\0") if p]
added = sorted(p for p in tracked if matches(p) and p not in recorded)

for label, items in (("MODIFIED", mismatched), ("MISSING", missing), ("ADDED", added)):
    for it in items:
        print(f"{label}\t{it}")
PY
)"
py_rc=$?
if [ "$py_rc" -ne 0 ]; then
  echo "check-integrity: ERROR - content check failed to run." >&2
  echo "$content_report" >&2
  exit 2
fi

if [ -z "$content_report" ]; then
  file_count="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["file_count"])' "$MANIFEST" 2>/dev/null || echo "?")"
  echo "check-integrity: content OK - all $file_count framework-surface files match the signed manifest (mode=$mode)."
  exit 0
fi

# There are content differences.
if [ "$mode" = "fork" ]; then
  {
    echo ""
    echo "=============================================================="
    echo " BLOCKED - fork altered the signed framework surface"
    echo "=============================================================="
    printf '%s\n' "$content_report" | sed 's/^/  /'
    echo ""
    echo "A downstream fork MUST NOT edit the framework surface. Customize"
    echo "by dependency injection at your own composition root instead."
    echo "See docs/roadmap/fork-and-sequencing/downstream-fork-guide.md § 3."
  } >&2
  exit 1
fi

# Upstream: advisory - the framework legitimately evolves here; re-sign.
{
  echo ""
  echo "--------------------------------------------------------------"
  echo " NOTICE - framework surface changed vs the signed manifest"
  echo "--------------------------------------------------------------"
  printf '%s\n' "$content_report" | sed 's/^/  /'
  echo ""
  echo "This is expected upstream. Regenerate + re-sign before release:"
  echo "  scripts/integrity/sign-integrity.sh"
} >&2
exit 0
