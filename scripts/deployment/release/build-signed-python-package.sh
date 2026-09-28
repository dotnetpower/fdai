#!/usr/bin/env bash
# Build one pip-installable offline wheelhouse with one detached signature.
set -euo pipefail
umask 077

repo_root="$(git rev-parse --show-toplevel)"
out=""
signing_key=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) out="$2"; shift 2 ;;
    --signing-key) signing_key="$2"; shift 2 ;;
    *) echo "build-signed-python-package: unsupported argument" >&2; exit 64 ;;
  esac
done

[[ "$out" = /* && "$signing_key" = /* ]] || {
  echo "build-signed-python-package: --out and --signing-key must be absolute paths" >&2
  exit 64
}
[[ ! -e "$out" && ! -L "$out" ]] || {
  echo "build-signed-python-package: a fresh output directory is required" >&2
  exit 3
}
[[ -f "$signing_key" && ! -L "$signing_key" && "$(stat -c '%a' "$signing_key")" == "600" ]] || {
  echo "build-signed-python-package: signing key must be a mode-0600 regular file" >&2
  exit 3
}
for tool in openssl sha256sum tar uv; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "build-signed-python-package: required tool is unavailable: $tool" >&2
    exit 3
  }
done

python="$repo_root/.venv/bin/python"
[[ -x "$python" ]] || {
  echo "build-signed-python-package: repository Python environment is required" >&2
  exit 3
}

package="$out/package"
wheels="$package/wheels"
install -d -m 0700 "$wheels"
version="$(
  PYTHONPATH="$repo_root/packages/deployment-cli/src" "$python" -c \
    'from fdai_deployment_cli.__about__ import __version__; print(__version__)'
)"
[[ "$version" =~ ^[0-9]+[.][0-9]+[.][0-9]+$ ]] || {
  echo "build-signed-python-package: package version is invalid" >&2
  exit 3
}

uv lock --check --project "$repo_root/packages/deployment-cli" >/dev/null
uv build --wheel --project "$repo_root/packages/deployment-cli" --out-dir "$wheels" >/dev/null
uv export --project "$repo_root/packages/deployment-cli" --locked --no-dev --no-emit-project \
  --format requirements-txt --output-file "$out/dependencies.txt" >/dev/null
UV_PROJECT_ENVIRONMENT="$out/release-env" uv run \
  --project "$repo_root/packages/deployment-cli" --locked --no-dev --group release \
  --python "$python" python -m pip download --only-binary=:all: --require-hashes \
  --dest "$wheels" --requirement "$out/dependencies.txt" >/dev/null
# uv build writes an unsigned .gitignore marker; the signed package holds only wheels.
rm -f -- "$wheels/.gitignore"
if find "$wheels" -mindepth 1 ! \( -type f -name '*.whl' \) -print -quit | grep -q .; then
  echo "build-signed-python-package: wheelhouse contains a non-wheel entry" >&2
  exit 3
fi

printf 'fdai-deployment-cli==%s\n' "$version" >"$package/requirements.txt"
cat >"$package/INSTALL.txt" <<'EOF'
Verify and install:

  openssl pkeyutl -verify -pubin -inkey <trusted-public-key.pem> \
    -rawin -in SHA256SUMS -sigfile SHA256SUMS.sig
  sha256sum -c SHA256SUMS
  python -m pip install --no-index --find-links wheels -r requirements.txt
EOF

PACKAGE_ROOT="$package" "$python" - <<'PY'
from __future__ import annotations

import hashlib
import os
from pathlib import Path

root = Path(os.environ["PACKAGE_ROOT"])
paths = [root / "INSTALL.txt", root / "requirements.txt", *sorted((root / "wheels").glob("*.whl"))]
if len(paths) < 3:
    raise SystemExit("build-signed-python-package: wheelhouse is empty")
lines = []
for path in paths:
    if not path.is_file() or path.is_symlink():
        raise SystemExit("build-signed-python-package: package input is invalid")
    lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(root).as_posix()}")
(root / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="ascii")
PY

openssl pkeyutl -sign -inkey "$signing_key" -rawin \
  -in "$package/SHA256SUMS" -out "$package/SHA256SUMS.sig"
openssl pkey -in "$signing_key" -pubout -out "$out/signer.pub" 2>/dev/null
archive="$out/fdai-deployment-cli-${version}-offline.tar.gz"
tar -czf "$archive" -C "$out" package
chmod 0600 "$archive" "$out/signer.pub" "$package/SHA256SUMS.sig"
rm -f "$out/dependencies.txt"
rm -rf -- "$out/release-env"

printf 'signed-python-package: OK package=%s archive=%s sha256=%s\n' \
  "$package" "$archive" "$(sha256sum "$archive" | cut -d' ' -f1)"
