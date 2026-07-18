#!/usr/bin/env bash
#
# sign-integrity.sh - UPSTREAM-ONLY signer for the framework-surface manifest.
#
# Signs security/integrity/manifest.json with an Ed25519 private key and writes
# the detached signature security/integrity/manifest.json.sig. Verification is
# done OFFLINE by anyone with the committed public key (scripts/integrity/check-integrity.sh).
#
# This raises the bar in three ways:
#   - tamper-EVIDENCE: any framework-surface edit changes the manifest hashes.
#   - non-forgeable ATTESTATION: without this private key a fork cannot mint a
#     manifest that verifies against the committed public key.
#   - OFFLINE: signing needs the private key; verification needs only the public
#     key + openssl. No network, no OCSP, no cert chain. Air-gapped friendly.
#
# It is NOT tamper-PROOF: a fork owner still controls their own runtime and can
# delete the verifier. Enforcement of trust is an upstream-controlled gate's job.
#
# Key handling:
#   - The PRIVATE key never enters the repo. Default path is secrets/ (which is
#     gitignored) or set FDAI_INTEGRITY_KEY to an out-of-tree path (recommended:
#     a path under $HOME or a hardware/KMS-backed signer).
#   - The PUBLIC key is committed at security/integrity/upstream-signing-key.pub
#     so every fork can verify offline.
#
# Usage:
#   scripts/integrity/sign-integrity.sh --gen-key   # one-time: create the Ed25519 keypair
#   scripts/integrity/sign-integrity.sh             # regenerate manifest (if needed) + sign
#   scripts/integrity/sign-integrity.sh --no-regen  # sign the manifest exactly as-is on disk
#
# Environment:
#   FDAI_INTEGRITY_KEY   private key path (default: secrets/integrity-signing-key.pem)

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root"

INTEGRITY_DIR="security/integrity"
MANIFEST="$INTEGRITY_DIR/manifest.json"
SIG="$INTEGRITY_DIR/manifest.json.sig"
PUBKEY="$INTEGRITY_DIR/upstream-signing-key.pub"
PRIVKEY="${FDAI_INTEGRITY_KEY:-secrets/integrity-signing-key.pem}"

command -v openssl >/dev/null 2>&1 || {
  echo "sign-integrity: ERROR - openssl not found on PATH." >&2
  exit 2
}
if command -v uv >/dev/null 2>&1; then
  python_cmd=(uv run python)
elif command -v python3 >/dev/null 2>&1; then
  python_cmd=(python3)
else
  echo "sign-integrity: ERROR - uv or python3 not found on PATH." >&2
  exit 2
fi

gen_key=0
regen=1
for arg in "$@"; do
  case "$arg" in
    --gen-key) gen_key=1 ;;
    --no-regen) regen=0 ;;
    -h | --help)
      sed -n '2,40p' "$0"
      exit 0
      ;;
    *)
      echo "sign-integrity: unknown argument '$arg'" >&2
      exit 2
      ;;
  esac
done

mkdir -p "$INTEGRITY_DIR"

if [ "$gen_key" = "1" ]; then
  if [ -f "$PRIVKEY" ]; then
    echo "sign-integrity: REFUSING to overwrite existing private key at $PRIVKEY" >&2
    echo "  Delete it deliberately first if you really mean to rotate the signing key." >&2
    exit 1
  fi
  mkdir -p "$(dirname "$PRIVKEY")"
  openssl genpkey -algorithm ed25519 -out "$PRIVKEY"
  chmod 600 "$PRIVKEY"
  openssl pkey -in "$PRIVKEY" -pubout -out "$PUBKEY"
  echo "sign-integrity: generated Ed25519 keypair."
  echo "  private (KEEP SECRET, out of git): $PRIVKEY"
  echo "  public  (COMMIT this):             $PUBKEY"
  echo "  Next: scripts/integrity/sign-integrity.sh    # regenerate manifest + sign"
  exit 0
fi

if [ ! -f "$PRIVKEY" ]; then
  echo "sign-integrity: ERROR - private key not found at $PRIVKEY." >&2
  echo "  Create one first: scripts/integrity/sign-integrity.sh --gen-key" >&2
  echo "  Or point FDAI_INTEGRITY_KEY at your signing key." >&2
  exit 1
fi

if [ "$regen" = "1" ]; then
  "${python_cmd[@]}" scripts/integrity/gen-integrity-manifest.py --out "$MANIFEST"
fi

if [ ! -f "$MANIFEST" ]; then
  echo "sign-integrity: ERROR - $MANIFEST is missing (run without --no-regen)." >&2
  exit 1
fi

# Ed25519 is a pure signature scheme (no prehash): sign the raw manifest bytes.
# The signature is stored base64-armored (ASCII) so the committed artifact is a
# text file, not a binary blob in the tree.
raw_sig="$(mktemp)"
trap 'rm -f "$raw_sig"' EXIT
openssl pkeyutl -sign -inkey "$PRIVKEY" -rawin -in "$MANIFEST" -out "$raw_sig"
base64 -w0 "$raw_sig" > "$SIG"
printf '\n' >> "$SIG"

# Self-check: verify immediately so we never commit a signature that does not
# validate against the committed public key.
if [ ! -f "$PUBKEY" ]; then
  echo "sign-integrity: ERROR - public key $PUBKEY missing; cannot self-verify." >&2
  exit 1
fi
base64 -d "$SIG" > "$raw_sig"
if openssl pkeyutl -verify -pubin -inkey "$PUBKEY" -rawin -sigfile "$raw_sig" -in "$MANIFEST" >/dev/null 2>&1; then
  echo "sign-integrity: signed and self-verified."
  echo "  manifest:  $MANIFEST"
  echo "  signature: $SIG"
  echo "  public:    $PUBKEY"
  echo "  Commit all three. Verify anywhere offline: scripts/integrity/check-integrity.sh"
else
  echo "sign-integrity: ERROR - signature did NOT verify against $PUBKEY." >&2
  echo "  The public key and private key may be a mismatched pair." >&2
  rm -f "$SIG"
  exit 1
fi
