# FDAI Deployment CLI

`fdai-deployment-cli` installs the `fdaictl` command. You can install it from a connected package
source or from a small signed offline wheelhouse. Package installation does not authenticate to
Azure or grant deployment authority.

## Install from a signed offline package

The offline package contains the CLI wheel, its dependency wheels, one requirements file, one
checksum list, and one detached Ed25519 signature.

Verify and install it with standard tools:

```bash
tar -xzf fdai-deployment-cli-0.1.1-offline.tar.gz
cd package
openssl pkeyutl -verify -pubin \
  -inkey /private/trusted-package-signer.pub \
  -rawin -in SHA256SUMS -sigfile SHA256SUMS.sig
sha256sum -c SHA256SUMS
python -m pip install --no-index --find-links wheels -r requirements.txt
fdaictl --version
```

The trusted public key should come from the operator, not from the package being verified. Pip
handles interpreter, ABI, platform, dependency, and installation compatibility.

## Build the offline package

Use one operator-held Ed25519 private key:

```bash
scripts/deployment/release/build-signed-python-package.sh \
  --out /private/fdai-python-package \
  --signing-key /private/deployment-signing-key.pem
```

The private key must be an owner-only mode-`0600` file. The builder produces:

```text
fdai-python-package/
  fdai-deployment-cli-0.1.1-offline.tar.gz
  signer.pub
  package/
    INSTALL.txt
    requirements.txt
    SHA256SUMS
    SHA256SUMS.sig
    wheels/
```

No TUF root, nested bundle signature, artifact profile, SBOM, provenance document, deployment
appliance, runtime image, or Azure receipt is required to complete the Python package.

## Install from a clone

For connected development, use the locked repository environment:

```bash
uv tool install --from ./packages/deployment-cli fdai-deployment-cli
fdaictl --version
```

See the
[deployment quickstart](../../docs/user-guide/deploy-quickstart.md#install-the-command-once)
for PATH setup, updates, and editable development.

## Use the command

Run `fdaictl --help` for the current command tree. Common entry points include:

| Command | Purpose |
|---------|---------|
| `fdaictl version` | Show the installed CLI version. |
| `fdaictl doctor` | Check local tools and Azure authentication. |
| `fdaictl provision inspect` | Inspect a target without changing it. |
| `fdaictl provision azure` | Start the guarded Azure deployment coordinator. |
| `fdaictl onboard guided --simulate` | Rehearse the finite stage graph without Azure changes. |

Package verification and Azure deployment are separate operations. Azure plans, approvals, Managed
Identity, recovery, migrations, service health, and cleanup remain deployment-owner controls after
the CLI is installed.

## Progress output

Interactive text mode shows the current deployment phase and elapsed time. Use `--progress plain`
for line-oriented logs, `--progress off` to hide progress, or `--output json` for machine output.
Progress is not readiness evidence; the final deployment receipts remain authoritative.

## Test

Run the package tests with:

```bash
uv run --project packages/deployment-cli pytest -q --no-cov packages/deployment-cli/tests
uv run pytest -q --no-cov tests/integration/scripts/test_package_assurance.py \
  tests/integration/scripts/test_signed_python_package.py
```

See [Package Assurance](../../docs/roadmap/architecture/package-assurance.md) for the minimal signing
contract and [Installable Deployment CLI](../../docs/roadmap/deployment/installable-deployment-cli.md)
for Azure deployment behavior.
