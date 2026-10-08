---
agent: agent
description: Fix detected FDAI security issues interactively from remediation pack {{PACK_ID}}.
argument-hint: "[scope: P0-P1 | severity-high | FG-001 | FDAI-SEC-<id>]"
---

Read the file `REMEDIATE.prompt.md` in the FDAI remediation pack directory
`${input:packDir:Path to the {{PACK_DIR}} directory}` and follow it exactly. Use that directory as
`<pack>` in every helper command.

Requested scope, if any: ${input:scope:Scope (leave empty to be asked)}
