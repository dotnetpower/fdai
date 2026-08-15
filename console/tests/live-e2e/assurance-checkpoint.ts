/** Resumable checkpoint for bounded live assurance runs. */

import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

import { canonicalJsonDigest } from "./browser-evidence-provenance";

export const ASSURANCE_CHECKPOINT_SCHEMA_VERSION = "1.0.0";

export interface AssuranceCheckpointBinding {
  readonly source_revision: string;
  readonly configuration_digest: string;
  readonly workspace_patch_digest: string;
}

export interface AssuranceCheckpointResult {
  readonly question_id: string;
}

export interface AssuranceCheckpoint<TResult extends AssuranceCheckpointResult> {
  readonly schema_version: string;
  readonly binding: AssuranceCheckpointBinding;
  readonly question_ids: readonly string[];
  readonly results_digest: string;
  readonly results: readonly TResult[];
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringArray(value: unknown): value is readonly string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function parseBinding(value: unknown): AssuranceCheckpointBinding | null {
  if (!isPlainObject(value)) return null;
  const { source_revision, configuration_digest, workspace_patch_digest } = value;
  if (
    typeof source_revision !== "string" || typeof configuration_digest !== "string" ||
    typeof workspace_patch_digest !== "string"
  ) {
    return null;
  }
  return { source_revision, configuration_digest, workspace_patch_digest };
}

/**
 * Parses a checkpoint and rejects anything malformed.
 *
 * A torn or corrupt checkpoint returns `null` so the caller restarts the cohort instead of
 * importing partial evidence.
 */
export function parseAssuranceCheckpoint<TResult extends AssuranceCheckpointResult>(
  raw: unknown,
): AssuranceCheckpoint<TResult> | null {
  if (!isPlainObject(raw)) return null;
  if (raw.schema_version !== ASSURANCE_CHECKPOINT_SCHEMA_VERSION) return null;
  const binding = parseBinding(raw.binding);
  if (binding === null) return null;
  if (!isStringArray(raw.question_ids) || raw.question_ids.length === 0) return null;
  if (new Set(raw.question_ids).size !== raw.question_ids.length) return null;
  if (typeof raw.results_digest !== "string") return null;
  if (!Array.isArray(raw.results)) return null;
  const questionIds = new Set(raw.question_ids);
  const seen = new Set<string>();
  for (const result of raw.results) {
    if (!isPlainObject(result) || typeof result.question_id !== "string") return null;
    if (!questionIds.has(result.question_id) || seen.has(result.question_id)) return null;
    seen.add(result.question_id);
  }
  const results = raw.results as readonly TResult[];
  if (canonicalJsonDigest(results) !== raw.results_digest) return null;
  return {
    schema_version: raw.schema_version,
    binding,
    question_ids: raw.question_ids,
    results_digest: raw.results_digest,
    results,
  };
}

/** Returns the previously completed results that the current run may reuse. */
export function resumableResults<TResult extends AssuranceCheckpointResult>(
  checkpoint: AssuranceCheckpoint<TResult> | null,
  expected: { readonly binding: AssuranceCheckpointBinding; readonly questionIds: readonly string[] },
): readonly TResult[] {
  if (checkpoint === null) return [];
  const { binding, questionIds } = expected;
  if (
    checkpoint.binding.source_revision !== binding.source_revision ||
    checkpoint.binding.configuration_digest !== binding.configuration_digest ||
    checkpoint.binding.workspace_patch_digest !== binding.workspace_patch_digest
  ) {
    return [];
  }
  if (checkpoint.question_ids.length !== questionIds.length) return [];
  if (checkpoint.question_ids.some((value, index) => value !== questionIds[index])) return [];
  return checkpoint.results;
}

/** Returns the cohort members that still need a live turn, preserving cohort order. */
export function pendingQuestions<TQuestion extends { readonly question_id: string }>(
  questions: readonly TQuestion[],
  completed: readonly AssuranceCheckpointResult[],
): readonly TQuestion[] {
  const completedIds = new Set(completed.map((result) => result.question_id));
  return questions.filter((question) => !completedIds.has(question.question_id));
}

export function buildAssuranceCheckpoint<TResult extends AssuranceCheckpointResult>(
  binding: AssuranceCheckpointBinding,
  questionIds: readonly string[],
  results: readonly TResult[],
): AssuranceCheckpoint<TResult> {
  return {
    schema_version: ASSURANCE_CHECKPOINT_SCHEMA_VERSION,
    binding,
    question_ids: questionIds,
    results_digest: canonicalJsonDigest(results),
    results,
  };
}

export async function readAssuranceCheckpoint<TResult extends AssuranceCheckpointResult>(
  path: string,
): Promise<AssuranceCheckpoint<TResult> | null> {
  let raw: string;
  try {
    raw = await readFile(path, "utf8");
  } catch {
    return null;
  }
  try {
    return parseAssuranceCheckpoint<TResult>(JSON.parse(raw));
  } catch {
    return null;
  }
}

/** Writes the checkpoint atomically so an interrupted run cannot leave a torn file. */
export async function writeAssuranceCheckpoint<TResult extends AssuranceCheckpointResult>(
  path: string,
  checkpoint: AssuranceCheckpoint<TResult>,
): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  const temporaryPath = `${path}.partial`;
  await writeFile(temporaryPath, `${JSON.stringify(checkpoint, null, 2)}\n`, "utf8");
  await rename(temporaryPath, path);
}
