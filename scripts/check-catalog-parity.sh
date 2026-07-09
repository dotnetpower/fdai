#!/usr/bin/env bash
#
# check-catalog-parity.sh - L2 message-catalog parity gate.
#
# Enforces the Product i18n rule in
# .github/instructions/language.instructions.md: the English catalog is the
# source of truth. A Korean catalog MAY lag (the mandatory English fallback
# covers any missing key) but MUST NOT invent keys the English catalog does
# not have. So for every sibling pair, keys(<name>.ko.json) MUST be a subset
# of keys(<name>.en.json). This mirrors the -ko.md SHA gate: the translation
# can trail the source, never diverge from it.
#
# Convention: a paired catalog is `<name>.en.json` (source) next to
# `<name>.ko.json` (translation) in the same directory. Keys are compared
# after flattening nested objects with '.'; arrays are treated as leaf
# values. Astro Starlight site locales are framework-managed and out of
# scope here.
#
# No catalogs present => passes (no-op), so this is safe to land before any
# catalog exists (i18n Phase 0/1). A `.en.json` with no `.ko.json` sibling is
# fine (translation not started yet).
#
# Exit codes: 0 on success, 1 on any orphan translation key.

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

mapfile -t en_catalogs < <(git ls-files -co --exclude-standard '*.en.json' | sort)

fail=0
checked=0
for en in "${en_catalogs[@]}"; do
  ko="${en%.en.json}.ko.json"
  [[ -f "$ko" ]] || continue
  checked=$((checked + 1))
  orphans="$(
    python3 - "$en" "$ko" <<'PY'
import json
import sys


def flatten(obj, prefix=""):
    keys = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                keys |= flatten(v, path)
            else:
                keys.add(path)
    return keys


try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        en_keys = flatten(json.load(fh))
    with open(sys.argv[2], encoding="utf-8") as fh:
        ko_keys = flatten(json.load(fh))
except (OSError, ValueError) as exc:
    print(f"__PARSE_ERROR__:{exc}")
    sys.exit(0)

for key in sorted(ko_keys - en_keys):
    print(key)
PY
  )"
  if [[ "$orphans" == __PARSE_ERROR__:* ]]; then
    echo "check-catalog-parity: FAIL could not parse pair ${en} / ${ko}: ${orphans#__PARSE_ERROR__:}"
    fail=1
    continue
  fi
  if [[ -n "$orphans" ]]; then
    echo "check-catalog-parity: FAIL ${ko} has keys absent from ${en}:"
    echo "$orphans" | sed 's/^/    /'
    fail=1
  fi
done

if [[ "$fail" -ne 0 ]]; then
  echo "check-catalog-parity: orphan translation keys found (see above)."
  echo "Fix: remove the key from the ko catalog, or add it to the en source"
  echo "(en is the source of truth; ko is a subset - missing keys fall back to en)."
  exit 1
fi

echo "check-catalog-parity: OK (${checked} en/ko catalog pair(s) verified)"
