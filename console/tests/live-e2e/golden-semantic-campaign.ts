import { readFile } from "node:fs/promises";
import path from "node:path";

export interface GoldenCampaignCase {
  readonly caseId: string;
  readonly locale: "en" | "ko";
  readonly prompt: string;
  readonly variationKind?: string;
  readonly oracle?: GoldenCampaignOracle;
}

export interface GoldenCampaignOracle {
  readonly operation: string;
  readonly subjectType: string;
  readonly temporalScope: string;
  readonly requiredCapabilities: readonly string[];
  readonly allowedDispositions: readonly string[];
  readonly requiredObjectTypes: readonly string[];
  readonly requiredLinkTypes: readonly string[];
  readonly requiredFunctionTypes: readonly string[];
  readonly requiredFactKinds: readonly string[];
  readonly requiredLimitations: readonly string[];
  readonly forbiddenClaims: readonly string[];
  readonly evidencePosture: string;
  readonly authorityPosture: "read_only" | "draft_only";
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

export interface GoldenSequenceResult {
  readonly completed: number;
  readonly stoppedReason: string | null;
}

export interface GoldenCampaignOptions {
  readonly readinessCount: number;
  readonly runFull: boolean;
  readonly perTurnTimeoutMs: number;
}

export interface GoldenSequenceOptions {
  readonly perTurnTimeoutMs: number;
  readonly pressureProbe: () => Promise<string | null>;
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
    readonly expectation_id: string;
    readonly variation_kind: string;
  }[];
}

interface GoldenCampaignLoadOptions {
  readonly variationKinds?: readonly string[];
  readonly expectedCaseCount?: number;
}

export async function loadGoldenCampaignCases(
  datasetRoot: string,
  options: GoldenCampaignLoadOptions = {},
): Promise<readonly GoldenCampaignCase[]> {
  const expectations = JSON.parse(
    await readFile(path.join(datasetRoot, "expectations.json"), "utf8"),
  ) as {
    readonly cases: readonly Record<string, unknown>[];
  };
  const coverage = JSON.parse(
    await readFile(path.join(datasetRoot, "coverage.json"), "utf8"),
  ) as {
    readonly expectations: readonly Record<string, unknown>[];
  };
  const expectationById = new Map(
    expectations.cases.map((item) => [String(item["semantic_pair_id"]), item]),
  );
  const coverageById = new Map(
    coverage.expectations.map((item) => [String(item["expectation_id"]), item]),
  );
  const selectedVariations = options.variationKinds === undefined
    ? null
    : new Set(options.variationKinds);
  const artifacts = await Promise.all(
    (["en", "ko"] as const).map(async (locale) => {
      const loaded = JSON.parse(
        await readFile(path.join(datasetRoot, `questions.${locale}.json`), "utf8"),
      ) as QuestionArtifact;
      if (loaded.schema_version !== "2.0.0" || loaded.locale !== locale) {
        throw new Error("golden question artifact identity is invalid");
      }
      return loaded.questions
        .filter((question) =>
          selectedVariations === null || selectedVariations.has(question.variation_kind)
        )
        .map((question) => ({
          caseId: `${question.case_id}.${locale}`,
          locale,
          prompt: question.question,
          variationKind: question.variation_kind,
          oracle: buildOracle(
            expectationById.get(question.expectation_id),
            coverageById.get(question.expectation_id),
          ),
        }));
    }),
  );
  const cases = artifacts.flat().sort((left, right) => left.caseId.localeCompare(right.caseId));
  const expectedCaseCount = options.expectedCaseCount ?? 560;
  if (
    cases.length !== expectedCaseCount ||
    new Set(cases.map((item) => item.caseId)).size !== cases.length
  ) {
    throw new Error(
      `golden campaign requires exactly ${expectedCaseCount} unique locale cases`,
    );
  }
  return cases;
}

function buildOracle(
  expectation: Record<string, unknown> | undefined,
  coverage: Record<string, unknown> | undefined,
): GoldenCampaignOracle {
  if (expectation === undefined || coverage === undefined) {
    throw new Error("golden campaign case references an unknown expectation");
  }
  const semantics = objectField(expectation, "expected_semantics");
  const retrieval = objectField(expectation, "semantic_retrieval");
  const answer = objectField(expectation, "answer_oracle");
  const operation = textField(semantics, "operation");
  return {
    operation,
    subjectType: textField(semantics, "subject_type"),
    temporalScope: textField(semantics, "temporal_scope"),
    requiredCapabilities: textArray(semantics, "required_capabilities"),
    allowedDispositions: textArray(semantics, "allowed_dispositions"),
    requiredObjectTypes: textArray(retrieval, "required_object_types"),
    requiredLinkTypes: textArray(retrieval, "required_link_types"),
    requiredFunctionTypes: textArray(retrieval, "required_function_types"),
    requiredFactKinds: textArray(answer, "required_fact_kinds"),
    requiredLimitations: textArray(answer, "required_limitations"),
    forbiddenClaims: textArray(answer, "forbidden_claims"),
    evidencePosture: textField(coverage, "evidence_posture"),
    authorityPosture: operation === "action_draft" ? "draft_only" : "read_only",
  };
}

export async function executeGoldenCampaign(
  cases: readonly GoldenCampaignCase[],
  submit: GoldenCampaignSubmit,
  options: GoldenCampaignOptions,
): Promise<GoldenCampaignResult> {
  if (options.readinessCount < 1 || options.readinessCount > 3) {
    throw new Error("golden readiness count MUST be in [1, 3]");
  }
  validateTurnTimeout(options.perTurnTimeoutMs);
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

export function selectGoldenCampaignRange(
  cases: readonly GoldenCampaignCase[],
  startIndex: number,
  endIndexExclusive: number,
): readonly GoldenCampaignCase[] {
  if (
    !Number.isInteger(startIndex) ||
    !Number.isInteger(endIndexExclusive) ||
    startIndex < 0 ||
    endIndexExclusive > cases.length ||
    startIndex >= endIndexExclusive
  ) {
    throw new Error("golden campaign range is invalid");
  }
  return cases.slice(startIndex, endIndexExclusive);
}

export async function executeGoldenSequence(
  cases: readonly GoldenCampaignCase[],
  submit: GoldenCampaignSubmit,
  options: GoldenSequenceOptions,
): Promise<GoldenSequenceResult> {
  validateTurnTimeout(options.perTurnTimeoutMs);
  if (cases.length === 0) throw new Error("golden sequence MUST contain at least one case");

  let completed = 0;
  for (const campaignCase of cases) {
    const pressureBefore = await options.pressureProbe();
    if (pressureBefore !== null) return { completed, stoppedReason: pressureBefore };
    const turnReason = await submitOnce(
      campaignCase,
      "full",
      submit,
      options.perTurnTimeoutMs,
    );
    if (turnReason !== null) return { completed, stoppedReason: turnReason };
    const pressureAfter = await options.pressureProbe();
    if (pressureAfter !== null) return { completed, stoppedReason: pressureAfter };
    completed += 1;
  }
  return { completed, stoppedReason: null };
}

function readinessCases(
  cases: readonly GoldenCampaignCase[],
  count: number,
): readonly GoldenCampaignCase[] {
  const selected: GoldenCampaignCase[] = [];
  for (const locale of ["en", "ko"] as const) {
    const campaignCase = cases.find((candidate) => candidate.locale === locale);
    if (campaignCase !== undefined) selected.push(campaignCase);
    if (selected.length === count) return selected;
  }
  for (const campaignCase of cases) {
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
    return pressureReason(turn) ?? typedOracleReason(campaignCase, turn);
  } catch (error) {
    return error instanceof Error && error.message === "golden_turn_timeout"
      ? "timeout"
      : "turn_error";
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}

function validateTurnTimeout(timeoutMs: number): void {
  if (timeoutMs < 1_000 || timeoutMs > 90_000) {
    throw new Error("golden per-turn timeout MUST be in [1000, 90000]");
  }
}

export function pressureReason(turn: GoldenCampaignTurn): string | null {
  const source = turn.source.toLowerCase();
  if (source.includes("429")) return "http_429";
  if (source.includes("503")) return "http_503";
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

export function typedOracleReason(
  campaignCase: GoldenCampaignCase,
  turn: GoldenCampaignTurn,
): string | null {
  if (campaignCase.oracle === undefined) return null;
  const receipt = turn.semanticReceipt as Record<string, unknown>;
  if (receipt["execution_authority"] !== false) return "execution_authority_present";
  if (!campaignCase.oracle.allowedDispositions.includes(String(receipt["disposition"]))) {
    return "disposition_mismatch";
  }
  const assurance = receipt["assurance_observation"] as Record<string, unknown>;
  if (assurance["execution_authority"] !== false) return "assurance_authority_present";
  const frame = assurance["frame"] as Record<string, unknown> | null;
  if (frame === null || typeof frame !== "object") return "semantic_frame_missing";
  const frameSubjects = textValues(frame["subject_types"]);
  const allowedFrameSubjects = new Set(campaignCase.oracle.requiredObjectTypes);
  if (
    frame["operation"] !== campaignCase.oracle.operation ||
    frame["temporal_scope"] !== campaignCase.oracle.temporalScope ||
    !frameSubjects.includes(campaignCase.oracle.subjectType) ||
    frameSubjects.some((subject) => !allowedFrameSubjects.has(subject))
  ) {
    return "semantic_frame_mismatch";
  }
  if (assurance["authority_posture"] !== campaignCase.oracle.authorityPosture) {
    return "authority_posture_mismatch";
  }
  const claims = new Set(textValues(assurance["claim_kinds"]));
  if (campaignCase.oracle.forbiddenClaims.some((value) => claims.has(value))) {
    return "forbidden_claim_present";
  }
  if (receipt["disposition"] !== "answered") return null;
  for (const [field, required] of [
    ["capabilities", campaignCase.oracle.requiredCapabilities],
    ["object_types", campaignCase.oracle.requiredObjectTypes],
    ["link_types", campaignCase.oracle.requiredLinkTypes],
    ["function_types", campaignCase.oracle.requiredFunctionTypes],
    ["fact_kinds", campaignCase.oracle.requiredFactKinds],
    ["limitation_kinds", campaignCase.oracle.requiredLimitations],
  ] as const) {
    const observed = new Set(textValues(assurance[field]));
    if (required.some((value) => !observed.has(value))) return `${field}_mismatch`;
  }
  if (
    assurance["evidence_posture"] !== campaignCase.oracle.evidencePosture
  ) {
    return "evidence_posture_mismatch";
  }
  return null;
}

function objectField(value: Record<string, unknown>, key: string): Record<string, unknown> {
  const item = value[key];
  if (typeof item !== "object" || item === null || Array.isArray(item)) {
    throw new Error(`golden campaign ${key} is malformed`);
  }
  return item as Record<string, unknown>;
}

function textField(value: Record<string, unknown>, key: string): string {
  const item = value[key];
  if (typeof item !== "string" || item.length === 0) {
    throw new Error(`golden campaign ${key} is malformed`);
  }
  return item;
}

function textArray(value: Record<string, unknown>, key: string): readonly string[] {
  const item = value[key];
  if (!Array.isArray(item) || item.some((entry) => typeof entry !== "string")) {
    throw new Error(`golden campaign ${key} is malformed`);
  }
  return item as string[];
}

function textValues(value: unknown): readonly string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}
