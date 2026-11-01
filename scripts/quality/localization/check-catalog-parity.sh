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

python3 - "${en_catalogs[@]}" <<'PY'
import json
import os
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


fail = 0
checked = 0
for en in sys.argv[1:]:
    ko = f"{en[:-8]}.ko.json" if en.endswith(".en.json") else f"{en}.ko.json"
    if not os.path.isfile(ko):
        continue
    checked += 1
    try:
        with open(en, encoding="utf-8") as fh:
            en_keys = flatten(json.load(fh))
        with open(ko, encoding="utf-8") as fh:
            ko_keys = flatten(json.load(fh))
    except (OSError, ValueError) as exc:
        print(f"check-catalog-parity: FAIL could not parse pair {en} / {ko}: {exc}")
        fail = 1
        continue
    orphans = sorted(ko_keys - en_keys)
    if orphans:
        print(f"check-catalog-parity: FAIL {ko} has keys absent from {en}:")
        for key in orphans:
            print(f"    {key}")
        fail = 1

if fail:
    print("check-catalog-parity: orphan translation keys found (see above).")
    print("Fix: remove the key from the ko catalog, or add it to the en source")
    print("(en is the source of truth; ko is a subset - missing keys fall back to en).")
    sys.exit(1)

print(f"check-catalog-parity: OK ({checked} en/ko catalog pair(s) verified)")
PY
