---
name: vscode-profile-onboarding
description: "Configure, validate, troubleshoot, or explain the shared FDAI VS Code Profile and local servers. Use when someone asks about VS Code setup, Profiles, extensions, WSL remote settings, editor slowness, onboarding, importing fdai.code-profile, or starting, running, restarting, or checking the Console web, design mock server, backend, local servers, or full stack."
argument-hint: "Set up or diagnose the FDAI VS Code Profile"
---

# FDAI VS Code Profile Onboarding

Use the repository artifacts as the source of truth. Do not reconstruct the profile from a
maintainer's local VS Code state.

## Source of truth

- [../../../.vscode/fdai.code-profile](../../../.vscode/fdai.code-profile) contains portable
  profile settings and extensions.
- [../../../.vscode/extensions.json](../../../.vscode/extensions.json) is the canonical extension
  recommendation and unwanted-extension list.
- [../../../.vscode/fdai.machine-settings.json](../../../.vscode/fdai.machine-settings.json)
  contains path-free WSL remote machine settings that VS Code Profile sync does not carry.
- [../../../scripts/automation/configure-vscode-profile.py](../../../scripts/automation/configure-vscode-profile.py)
  validates drift and safely merges remote machine settings.
- [../../../DEVELOPING.md](../../../DEVELOPING.md#1-vs-code-profile-recommended) is the human
  onboarding checklist.

## Procedure

1. Detect whether the current window is local, SSH, a dev container, or WSL. Use `code --status`
   when available. Never infer the remote type only from the host OS.
2. Run `python3 scripts/automation/configure-vscode-profile.py` from the repository root. Stop on
   artifact drift; do not improvise a different extension list.
3. If the window is WSL, run:

   ```bash
   python3 scripts/automation/configure-vscode-profile.py \
     --apply-machine-settings --check-machine-settings
   ```

   The merger preserves unrelated JSON settings. If the existing file is JSONC, it fails without
   writing. In that case, explain the conflict and merge the template with a structured JSONC-aware
   editor instead of stripping comments.
4. Ask the collaborator to run `Profiles: Import Profile`, select
   `.vscode/fdai.code-profile`, review the Settings and Extensions sections, and create or replace
   `FDAI`. Profile import is a user-visible VS Code action; do not edit VS Code profile databases.
5. Ask the collaborator to switch with `Profiles: Switch Profile`, select `FDAI`, and reopen this
   repository in WSL when WSL is the development target.
6. Verify the active profile from the title bar or Manage-button badge. Confirm that HashiCorp
   Terraform is active and Microsoft Terraform is not installed in this profile.
7. Run the validator again with `--check-machine-settings` in WSL and report any remaining gap.

## Local server start requests

- Treat an unqualified request to start the Console, Console web, local server, servers, backend,
  or full stack as a request for the complete `Console Web: Full Stack` topology. Start or verify
  all three required processes: `Console Web: Core Runtime`, `Console Web: Operator API`, and
  `Console Web: Frontend`. A listening frontend or Operator API alone is not a complete start.
- Use the existing VS Code tasks or launch configurations. Run `console: prepare full stack` before
  starting any missing backend process. Do not replace the standard browser Entra profile with a
  test, fixture, ingestion-gateway, or CLI-principal profile.
- A request that also names the design or mock server starts `design mocks: serve (5373)` in
  addition to the complete Console stack. The design server never substitutes for a Console
  backend process.
- Before reporting success, verify the Core Runtime process and Pantheon readiness, the Operator
  API on `127.0.0.1:8010`, the frontend on `127.0.0.1:5273`, and, when requested, the design server
  on `127.0.0.1:5373`. Do not infer backend readiness from a frontend HTTP `200` response.
- Start only the specifically named component when the user explicitly narrows the request, such as
  "frontend only", "Operator API only", or "design server only".

## Boundaries

- A profile configures editor behavior only. It never configures Azure accounts, tenants,
  subscriptions, endpoints, credentials, App Roles, runtime mode, promotion state, or executor
  identity.
- Do not commit exported local profile storage. It contains machine paths, UUIDs, versions, and
  timestamps. Update only the portable repository artifacts.
- Do not pin extension versions in the shared profile. Marketplace resolution selects the build
  for the collaborator's OS and remote environment.
- Settings Sync does not install remote extensions into WSL, SSH, or dev-container windows. Always
  validate inside the target remote window.
- Preserve personal keybindings, themes, snippets, MCP servers, UI state, and language models.
  They are intentionally absent from the shared profile.
