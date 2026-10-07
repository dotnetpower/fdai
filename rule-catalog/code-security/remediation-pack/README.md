# FDAI Remediation Pack {{PACK_ID}} (security fixes)

This pack lets you fix FDAI security findings in one interactive session with a coding agent such
as GitHub Copilot or Claude Code. The agent asks how far to go (triage, mitigate, fix, or harden),
works one fix group at a time, runs a guard on every change, and records a result file that you
return to FDAI. The pack expires at `{{EXPIRES_AT}}`.

> Keep this directory outside the repository, or add it to `.git/info/exclude`. It contains
> security findings that are not public. Do not commit it, attach it to a public issue, or share
> it outside your team. Delete it after you return the result.

## Requirements

- Python 3.10 or later and git on `PATH`. The helper uses only the Python standard library.
- A clean working tree at a commit that contains the pack's base commit.

## Start a session

Run the commands from the repository root. Replace `<pack>` with the path to `{{PACK_DIR}}`.

**GitHub Copilot (VS Code, agent mode):** copy `adapters/copilot/fdai-remediate.prompt.md` to your
user prompts folder or `.github/prompts/` (do not commit it), then run `/fdai-remediate`. You can
also attach `REMEDIATE.prompt.md` to the chat and ask the agent to follow it.

**Claude Code:** copy `adapters/claude/fdai-remediate.md` to `~/.claude/commands/`, then run
`/fdai-remediate <pack> P0-P1`. You can also ask: "Read `<pack>/REMEDIATE.prompt.md` and follow
it."

**Other agents:** add `adapters/AGENTS.snippet.md` to the agent's instructions, or ask the agent
to read and follow `REMEDIATE.prompt.md`.

## Check the pack yourself

```bash
python3 <pack>/tools/fdai_remediate.py --pack <pack> --repo . verify
python3 <pack>/tools/fdai_remediate.py --pack <pack> --repo . summary
```

## What happens to the result

The agent's statuses are claims. FDAI marks an issue fixed only after it rescans your commit with
equivalent coverage and the root cause is gone. FDAI decides false-positive claims through its
review process.

---

## 한국어 안내

이 팩은 GitHub Copilot이나 Claude Code 같은 코딩 에이전트와 대화하면서 FDAI 보안 결과를 한 번에
조치하도록 돕습니다. 에이전트는 조치 깊이(분류, 완화, 수정, 강화)를 묻고, fix group 단위로
작업하며, 모든 변경에 guard를 실행하고, FDAI에 돌려줄 결과 파일을 기록합니다.

- 이 디렉터리는 저장소 밖에 두거나 `.git/info/exclude`에 추가하세요. 공개되지 않은 보안 결과가
  들어 있으므로 커밋하거나 공개 이슈에 첨부하지 마세요.
- 시작 방법은 위 영어 안내와 같습니다. 에이전트에게 "`<pack>/REMEDIATE.prompt.md`를 읽고
  따르라"고 요청하면 됩니다.
- 결과의 상태 값은 주장일 뿐입니다. FDAI가 새 커밋을 다시 스캔해 근본 원인이 사라진 것을
  확인해야 수정 완료로 처리됩니다.
