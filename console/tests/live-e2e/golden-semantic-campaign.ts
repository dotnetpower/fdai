import { readFile } from "node:fs/promises";
import path from "node:path";

export interface GoldenCampaignCase {
  readonly caseId: string;
  readonly locale: "en" | "ko";
  readonly prompt: string;
  readonly runtimeContext: string;
}

export interface GoldenCampaignTurn {
  readonly source: string;
  readonly semanticReceipt: unknown;
}

export interface GoldenCampaignResult {
  readonly readinessCompleted: number;
  readonly fullStarted: boolean;
  readonly fullCompleted: number;
  readonly stoppedReason: string | null;
}

export interface GoldenCampaignOptions {
  readonly readinessCount: number;
  readonly runFull: boolean;
  readonly perTurnTimeoutMs: number;
}

export type GoldenCampaignSubmit = (
  campaignCase: GoldenCampaignCase,
  phase: "readiness" | "full",
) => Promise<GoldenCampaignTurn>;

interface QuestionArtifact {
  readonly schema_version: string;
  readonly locale: string;
  readonly questions: readonly {
    readonly case_id: string;
    readonly question: string;
    readonly runtime_context: string;
  }[];
}

export async function loadGoldenCampaignCases(
  datasetRoot: string,
): Promise<readonly GoldenCampaignCase[]> {
  const artifacts = await Promise.all(
    (["en", "ko"] as const).map(async (locale) => {
      const loaded = JSON.parse(
        await readFile(path.join(datasetRoot, `questions.${locale}.json`), "utf8"),
      ) as QuestionArtifact;
      if (loaded.schema_version !== "2.0.0" || loaded.locale !== locale) {
        throw new Error("golden question artifact identity is invalid");
      }
      return loaded.questions.map((question) => ({
        caseId: `${question.case_id}.${locale}`,
        locale,
        prompt: question.question,
        runtimeContext: question.runtime_context,
      }));
    }),
  );
  const cases = artifacts.flat().sort((left, right) => left.caseId.localeCompare(right.caseId));
  if (cases.length !== 560 || new Set(cases.map((item) => item.caseId)).size !== cases.length) {
    throw new Error("golden campaign requires exactly 560 unique locale cases");
  }
  return cases;
}

export async function executeGoldenCampaign(
  cases: readonly GoldenCampaignCase[],
  submit: GoldenCampaignSubmit,
  options: GoldenCampaignOptions,
): Promise<GoldenCampaignResult> {
  if (options.readinessCount < 1 || options.readinessCount > 3) {
    throw new Error("golden readiness count MUST be in [1, 3]");
  }
  if (options.perTurnTimeoutMs < 1_000 || options.perTurnTimeoutMs > 90_000) {
    throw new Error("golden per-turn timeout MUST be in [1000, 90000]");
  }
  if (cases.length < options.readinessCount) {
    throw new Error("golden campaign has fewer cases than its readiness probe");
  }

  let readinessCompleted = 0;
  for (const campaignCase of readinessCases(cases, options.readinessCount)) {
    const pressure = await submitOnce(campaignCase, "readiness", submit, options.perTurnTimeoutMs);
    if (pressure !== null) {
      return {
        readinessCompleted,
        fullStarted: false,
        fullCompleted: 0,
        stoppedReason: pressure,
      };
    }
    readinessCompleted += 1;
  }
  if (!options.runFull) {
    return {
      readinessCompleted,
      fullStarted: false,
      fullCompleted: 0,
      stoppedReason: null,
    };
  }

  let fullCompleted = 0;
  for (const campaignCase of cases) {
    const pressure = await submitOnce(campaignCase, "full", submit, options.perTurnTimeoutMs);
    if (pressure !== null) {
      return {
        readinessCompleted,
        fullStarted: true,
        fullCompleted,
        stoppedReason: pressure,
      };
    }
    fullCompleted += 1;
  }
  return {
    readinessCompleted,
    fullStarted: true,
    fullCompleted,
    stoppedReason: null,
  };
}

function readinessCases(
  cases: readonly GoldenCampaignCase[],
  count: number,
): readonly GoldenCampaignCase[] {
  const unbound = cases.filter((campaignCase) => campaignCase.runtimeContext === "none");
  const selected: GoldenCampaignCase[] = [];
  for (const locale of ["en", "ko"] as const) {
    const campaignCase = unbound.find((candidate) => candidate.locale === locale);
    if (campaignCase !== undefined) selected.push(campaignCase);
    if (selected.length === count) return selected;
  }
  for (const campaignCase of unbound) {
    if (!selected.includes(campaignCase)) selected.push(campaignCase);
    if (selected.length === count) return selected;
  }
  throw new Error("golden campaign has insufficient unbound readiness cases");
}

async function submitOnce(
  campaignCase: GoldenCampaignCase,
  phase: "readiness" | "full",
  submit: GoldenCampaignSubmit,
  timeoutMs: number,
): Promise<string | null> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const turn = await Promise.race([
      submit(campaignCase, phase),
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(() => reject(new Error("golden_turn_timeout")), timeoutMs);
      }),
    ]);
    return pressureReason(turn);
  } catch (error) {
    return error instanceof Error && error.message === "golden_turn_timeout"
      ? "timeout"
      : "turn_error";
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}

export function pressureReason(turn: GoldenCampaignTurn): string | null {
  const source = turn.source.toLowerCase();
  if (source.includes("429")) return "http_429";
  if (source.includes("timeout") || source.includes("timed out")) return "timeout";
  if (typeof turn.semanticReceipt !== "object" || turn.semanticReceipt === null) {
    return "semantic_receipt_missing";
  }
  const receipt = turn.semanticReceipt as Record<string, unknown>;
  if (receipt["schema_version"] !== "2.0.0") return "semantic_receipt_untyped";
  if (receipt["unavailable_reason"] === "semantic_planner_unavailable") {
    return "semantic_planner_unavailable";
  }
  const reason = receipt["reason_code"];
  if (reason === "semantic_deadline_exceeded") return "timeout";
  if (receipt["assurance_observation"] == null) return "assurance_observation_missing";
  return null;
}
