# FDAI Code Assurance

`fdai-code-assurance` is an optional FDAI extension package for read-only code and security review of bounded GitHub pull-request patches. It stays outside the base FDAI wheel and adds no agent, write credential, review-posting action, or executor authority.

## Capabilities

The package contributes two shadow-first reasoning tools:

| Capability | Tool | Scope |
|------------|------|-------|
| Code review | `code-assurance.review-pr` | Deterministic correctness checks on added patch lines |
| Security review | `code-assurance.security-review` | Credential, dynamic-code, command, TLS, and deserialization checks |

Both tools return immutable base and head commit SHAs, reviewed-file coverage, omitted patch files, and structured findings. Credential-like source text is never returned. A finding carries only its rule id, severity, path, line, message, and evidence SHA-256.

> GitHub may omit `patch` for binary or oversized files. The package reports those paths in `omitted_patch_files` and does not claim complete review coverage.

## Security boundary

Use a GitHub App installation token with only `Pull requests: read` repository permission. Public pull requests can use an empty token provider.

The package:

- validates `owner/repository` and a positive pull-request number;
- caps files, response bytes, and total patch characters;
- reads pull-request metadata before and after file pagination;
- discards all collected evidence if base SHA, head SHA, or changed-file count changes;
- rejects redirects and credential-bearing API base URLs;
- omits GitHub response bodies from errors;
- exposes no GitHub write, approval, merge, comment, or check-run operation.

## Compose the package

A fork composition root creates the read-only source and installs the capability bundle:

```python
import httpx

from fdai_code_assurance import (
	GitHubPullRequestSource,
	GitHubReviewSourceConfig,
	install_code_assurance_capabilities,
)

source = GitHubPullRequestSource(
	config=GitHubReviewSourceConfig(),
	http_client=httpx.AsyncClient(),
	token_provider=token_provider,
)
container = install_code_assurance_capabilities(container, source=source)
```

The helper is for a reviewed image composition root. For durable extension lifecycle, build a digest-bound package with `build_code_assurance_extension(...)`, then pass it through FDAI's `TrustedArtifactInstaller` and `ExtensionManager`. Installation starts disabled. Enabling the extension does not promote either reasoning tool out of shadow mode.

## Governed skills

`load_code_assurance_assets()` returns exact bytes for:

- `code-assurance.code-review` version `1.0.0`;
- `code-assurance.security-review` version `1.0.0`;
- `code-assurance.review-pack` version `1.0.0`.

Install the two skills and bundle through the existing signed skill workshop and trusted-artifact lifecycle. Loading a skill cannot add a tool or grant authority; the required package tool must already be available.

## Verification

From the repository root, run focused checks:

```bash
uv run ruff check extensions/code-assurance/src extensions/code-assurance/tests
uv run mypy --strict extensions/code-assurance/src/fdai_code_assurance
PYTHONPATH=extensions/code-assurance/src uv run pytest -q --no-cov extensions/code-assurance/tests/test_analyzer.py
PYTHONPATH=extensions/code-assurance/src uv run pytest -q --no-cov extensions/code-assurance/tests/test_github.py
PYTHONPATH=extensions/code-assurance/src uv run pytest -q --no-cov extensions/code-assurance/tests/test_bundle.py
uv build --package fdai-code-assurance
```
