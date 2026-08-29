# FDAI Deployment CLI

This package provides the installable `fdaictl` deployment surface. It validates local
configuration, verifies signed deployment artifacts, and prepares resumable subscription-genesis
work without granting runtime execution authority.

## Commands

Run `fdaictl --help` for the current command tree. Commands default to read-only behavior, produce
stable JSON with `--output json`, and keep secrets out of command arguments and output.

Use `fdaictl onboard guided --simulate` to rehearse the complete stage graph without Azure
authentication or mutation. The rehearsal writes a private hash-chained journal and resumes
completed stages without duplicating them.

## Testing

```bash
uv run --project packages/deployment-cli python -m pytest \
  -c packages/deployment-cli/pyproject.toml -q packages/deployment-cli/tests
```
