import { describe, expect, it } from "vitest";
import {
  buildSkillSourcesViewModel,
  decodeSkillSourceProjection,
} from "./skill-sources.model";

const SAMPLE_PROJECTION = {
  read_only: true,
  execution_authority: "none",
  sources: [
    {
      source_id: "operations-skills",
      kind: "github_repository",
      location: "example-org/skills",
      trust_tier: "organization_approved",
      owner: "platform-team",
      allowed_path: "skills/example",
      refresh_policy: "scheduled",
      refresh_interval_seconds: 3600,
      enabled: false,
      revision: "rev-1",
      last_refresh_at: null,
      next_refresh_at: null,
      last_etag: null,
      last_revision: null,
      error_count: 0,
      retry_at: null,
      last_error_kind: null,
    },
    {
      source_id: "resilience-skills",
      kind: "github_repository",
      location: "example-org/resilience",
      trust_tier: "organization_approved",
      owner: "sre-team",
      allowed_path: "skills/resilience",
      refresh_policy: "scheduled",
      refresh_interval_seconds: 1800,
      enabled: true,
      revision: "rev-2",
      last_refresh_at: "2026-11-01T00:00:00Z",
      next_refresh_at: "2026-11-01T00:30:00Z",
      last_etag: '"etag-1"',
      last_revision: "a".repeat(40),
      error_count: 0,
      retry_at: null,
      last_error_kind: null,
    },
  ],
  candidates: [
    {
      candidate_id: "skill-update-1",
      source_id: "resilience-skills",
      quarantine_id: "skill-quarantine-1",
      artifact_digest: "b".repeat(64),
      prior_installed_digest: null,
      created_at: "2026-11-01T00:00:00Z",
      verdict: "pass",
      state: "proposed",
      disabled: true,
    },
  ],
  revocations: [],
};

describe("skill-sources.model", () => {
  it("decodes read-only skill source projections and builds bilingual view models", () => {
    const decoded = decodeSkillSourceProjection(SAMPLE_PROJECTION);
    expect(decoded.read_only).toBe(true);
    expect(decoded.execution_authority).toBe("none");
    expect(decoded.sources[0]?.enabled).toBe(false);
    expect(decoded.candidates[0]?.disabled).toBe(true);

    const enView = buildSkillSourcesViewModel(decoded, "en");
    expect(enView.readOnly).toBe(true);
    expect(enView.executionAuthority).toBe("none");
    expect(enView.canApproveInConsole).toBe(false);
    expect(enView.canRevokeInConsole).toBe(false);
    expect(enView.enabledSourceCount).toBe(1);
    expect(enView.revokedSourceCount).toBe(0);
    expect(enView.sources[0]?.status).toBe("disabled_by_default");
    expect(enView.sources[0]?.statusLabel).toBe("Disabled by default");
    expect(enView.sources[1]?.status).toBe("ready");
    expect(enView.sources[1]?.candidateCount).toBe(1);

    const koView = buildSkillSourcesViewModel(decoded, "ko");
    expect(koView.title).toBe("외부 스킬 소스");
    expect(koView.sources[0]?.statusLabel).toBe("기본 비활성화");
    expect(koView.sources[1]?.statusLabel).toBe("새로고침 검증됨");
    expect(koView.canApproveInConsole).toBe(false);
    expect(koView.canRevokeInConsole).toBe(false);
  });

  it("rejects non-read-only, authority-bearing, enabled-candidate, or secret-bearing payloads", () => {
    expect(() =>
      decodeSkillSourceProjection({ ...SAMPLE_PROJECTION, read_only: false }),
    ).toThrow(/read_only/);
    expect(() =>
      decodeSkillSourceProjection({ ...SAMPLE_PROJECTION, execution_authority: "execute" }),
    ).toThrow(/execution_authority/);
    expect(() =>
      decodeSkillSourceProjection({
        ...SAMPLE_PROJECTION,
        candidates: [{ ...SAMPLE_PROJECTION.candidates[0], disabled: false }],
      }),
    ).toThrow(/disabled MUST remain true/);
    expect(() =>
      decodeSkillSourceProjection({
        ...SAMPLE_PROJECTION,
        bearer_token: "secret-value",
      }),
    ).toThrow(/MUST NOT expose secret field/);

    expect(() =>
      decodeSkillSourceProjection({
        ...SAMPLE_PROJECTION,
        sources: [SAMPLE_PROJECTION.sources[0], SAMPLE_PROJECTION.sources[0]],
      }),
    ).toThrow(/source_id .* is duplicated/);

    expect(() =>
      decodeSkillSourceProjection({
        ...SAMPLE_PROJECTION,
        candidates: [SAMPLE_PROJECTION.candidates[0], SAMPLE_PROJECTION.candidates[0]],
      }),
    ).toThrow(/candidate_id .* is duplicated/);

    expect(() =>
      decodeSkillSourceProjection({
        ...SAMPLE_PROJECTION,
        sources: [{ ...SAMPLE_PROJECTION.sources[0], refresh_interval_seconds: 120 }],
      }),
    ).toThrow(/refresh_interval_seconds MUST be between 300 and 604800/);

    expect(() =>
      decodeSkillSourceProjection({
        ...SAMPLE_PROJECTION,
        sources: [{ ...SAMPLE_PROJECTION.sources[0], refresh_interval_seconds: 700000 }],
      }),
    ).toThrow(/refresh_interval_seconds MUST be between 300 and 604800/);
  });
});
