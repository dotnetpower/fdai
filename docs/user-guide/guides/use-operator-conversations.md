---
title: Ask FDAI in conversation
description: How FDAI breaks a compound question into bounded parts, what a partial answer means, and why a change you ask for in chat comes back as a draft.
---

# Ask FDAI in conversation

Real operational questions rarely have one part. You ask why checkout is slow and whether it's
costing you money, in the same breath. FDAI plans that kind of question as a small graph of bounded
sub-questions, runs the independent ones, and joins the evidence into one answer.

This guide explains what that planning does for you, how to read an answer that only partly
succeeded, and why asking for a change gets you a draft rather than a change.

> **Conversation explains authority, it doesn't grant it.** The planner can't execute, approve,
> promote, or change policy. Anything that would alter your cloud leaves the conversation as a typed
> proposal and goes through the normal safety, approval, and audit path.

## What planning does with your question

Instead of forcing your sentence into a single tool call, FDAI turns it into goals with declared
dependencies. Each goal names its intent, the capability it needs, validated arguments, and how much
evidence it requires.

Example: you ask "why is checkout slow and is it costing us money." FDAI can separate the
performance question from the cost question, run them independently because neither depends on the
other, and then present both answers together with their own evidence.

The practical benefit is that one weak part of your question doesn't sink the rest of it.

## Reading a partial answer

When one branch succeeds and another doesn't, you get the successful part plus an honest account of
what failed. Successful siblings aren't dropped just because a neighbor had trouble.

| Branch state | Meaning |
|--------------|---------|
| Completed | The sub-question was answered |
| Unavailable | The request was rejected or the source couldn't answer |
| Failed | Something went wrong while running it |
| Timed out | It exceeded its bound |
| Cancelled | It was stopped before finishing |

Answers also declare what they're built on, so you can tell an answer grounded in your operational
data from one drawn from general model knowledge. When evidence is too thin, the answer is held for
review instead of being presented as fact.

Treat a partial answer as partial. The half that succeeded is real, and the half that didn't is not
evidence of a healthy system.

## Why a change request comes back as a draft

Ask FDAI to fix something and it produces a typed draft, not an applied change. The conversation
posture is explicit: read questions advise, and change requests draft.

That is the same boundary described in
[Agent-driven automation](../concepts/ontology-driven-automation.md). A draft still has to pass the
safety check, risk classification, approval, impact-scope limit, rollback contract, and audit
record that every other action passes. Phrasing a request conversationally doesn't shorten that
path, and it doesn't widen what your role can do.

## Streaming and one-shot

You can get an answer either way, and the difference matters mostly when a question takes a while.

- **One-shot** returns once the server has the final answer.
- **Streaming** shows branches starting and finishing as they go, along with provisional text that
  can still change.

Only the final frame is canonical. Text you saw mid-stream is a progress indication, not a recorded
answer, so quote the completed response rather than something you watched scroll past. When a
channel can't stream, FDAI sends one complete response rather than pretending precomputed chunks
are live.

## Getting better answers

- **Name the scope.** A service, resource group, or time window narrows every branch at once.
- **Ask compound questions on purpose.** Related sub-questions share correlation, which makes the
  joined answer more useful than two separate chats.
- **Read the evidence line.** If the answer says it's held for review, the useful next step is
  usually supplying the missing scope rather than rephrasing.

## Next steps

| To learn about | Read |
|----------------|------|
| What happens when your role can't run a command | [Approvals and channels](../concepts/approvals-and-channels.md) |
| How a drafted change is judged | [Trust tiers](../concepts/risk-tiers.md) |
| Why a plain-language query holds instead of guessing | [Agent-driven automation](../concepts/ontology-driven-automation.md) |
| How to ask a bounded question about a resource | [Investigate an Azure resource](investigate-azure-resources.md) |
| The full conversation planning contract | [Hierarchical conversation planning](../../roadmap/interfaces/hierarchical-conversation-planning.md) |
