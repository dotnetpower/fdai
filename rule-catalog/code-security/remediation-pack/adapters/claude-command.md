---
description: Remediate FDAI security findings interactively from a remediation pack.
argument-hint: "<path to {{PACK_DIR}}> [scope: P0-P1 | severity-high | FG-001 | FDAI-SEC-<id>]"
allowed-tools: Read, Edit, Write, Grep, Glob, Bash(python3:*), Bash(git status:*), Bash(git diff:*), Bash(git log:*)
---

Arguments: $ARGUMENTS

The first argument is the FDAI remediation pack directory. Read `REMEDIATE.prompt.md` in that
directory and follow it exactly, using that directory as `<pack>` in every helper command. Any
remaining argument is the requested scope for the first interview question.
