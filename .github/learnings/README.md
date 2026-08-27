# Coding-Agent Learning Inbox

This directory holds short-lived, non-authoritative observations that are not ready for a test,
design, instruction, or skill. Use the
[`feedback-learning`](../skills/feedback-learning/SKILL.md) skill to classify and maintain entries.

## Limits

- Keep at most 10 active topic files.
- Keep active topic content at or below 8 KB in total.
- Do not load the directory globally. Read only files whose scope matches the current task.
- Never store secrets, customer data, raw prompts, raw logs, or deployment identifiers.
- Promote, merge, or remove an entry as soon as its review condition is met.

## Entry Format

Create one ASCII-named Markdown file per topic:

```markdown
# Topic

- Scope: `path-or-subsystem`
- Observed: `YYYY-MM-DD`
- Evidence: concise local or repository evidence
- Review condition: the event that confirms, disproves, or expires this observation
- Candidate destination: test, design, instruction, skill, or remove

Describe the reusable observation in no more than five sentences.
```
An entry records a hypothesis. It never authorizes runtime behavior, permissions, approval,
deployment, or execution.
deployment, or execution.
