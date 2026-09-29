import { afterEach, describe, expect, it, vi } from "vitest";
import {
  decodePythonTaskAvailability,
  newPythonTaskRunIdempotencyKey,
  pythonTaskDraftKey,
  pythonTaskGenerationCanApply,
  requestPythonTaskRun,
  validatePythonTask,
  type PythonTaskDraft,
} from "./python-task";

const TASK: PythonTaskDraft = {
  task_id: "gpu.health-check",
  version: "1.0.0",
  entrypoint: "main.py",
  files: [{ path: "main.py", content: "import torch\nprint(torch.cuda.is_available())\n" }],
  required_modules: ["torch"],
  capabilities: ["gpu"],
  timeout_seconds: 300,
  python_executable: "/usr/bin/python3",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Python task authoring client", () => {
  it("decodes the server operation capability manifest", () => {
    const decoded = decodePythonTaskAvailability({
      available: true,
      operations: {
        generate: false,
        validate: true,
        stage: true,
        test: true,
        request_run: false,
        schedule: true,
      },
    });
    expect(decoded.available && decoded.operations.generate).toBe(false);
    expect(decoded.available && decoded.operations.validate).toBe(true);
    expect(() => decodePythonTaskAvailability({ available: true, operations: {} })).toThrow(
      "invalid response",
    );
  });

  it("decodes an explicit server-reported unavailable state", () => {
    const disabled = {
      generate: false,
      validate: false,
      stage: false,
      test: false,
      request_run: false,
      schedule: false,
    };
    expect(decodePythonTaskAvailability({
      schema_version: "1.0.0",
      available: false,
      unavailable_reasons: ["python_task_validator_not_bound", "python_task_vm_runner_not_bound"],
      operations: disabled,
      vm_task_runner: { bound: false },
      execution_authority: false,
    })).toEqual({
      available: false,
      reasons: ["python_task_validator_not_bound", "python_task_vm_runner_not_bound"],
    });
    for (const invalid of [
      { available: false, unavailable_reasons: [], operations: disabled },
      { available: false, operations: disabled },
      { available: false, unavailable_reasons: [""], operations: disabled },
      { available: false, unavailable_reasons: [7], operations: disabled },
      {
        available: false,
        unavailable_reasons: ["python_task_vm_runner_not_bound"],
        operations: { ...disabled, validate: true },
      },
      { available: "false", unavailable_reasons: ["x"], operations: disabled },
    ]) {
      expect(() => decodePythonTaskAvailability(invalid)).toThrow("invalid response");
    }
  });

  it("binds a staged artifact to every execution-relevant draft field", () => {
    const key = pythonTaskDraftKey(TASK);
    expect(pythonTaskDraftKey({ ...TASK, entrypoint: "worker.py" })).not.toBe(key);
    expect(pythonTaskDraftKey({ ...TASK, required_modules: ["torch", "numpy"] })).not.toBe(key);
    expect(pythonTaskDraftKey({ ...TASK, timeout_seconds: 301 })).not.toBe(key);
    expect(pythonTaskDraftKey({ ...TASK, capabilities: ["gpu", "network"] })).not.toBe(key);
  });

  it("discards generation results after a manual draft edit", () => {
    expect(pythonTaskGenerationCanApply(4, 3)).toBe(false);
    expect(pythonTaskGenerationCanApply(4, 4)).toBe(true);
  });

  it("creates a fresh bounded idempotency key for each immediate run", () => {
    const first = newPythonTaskRunIdempotencyKey();
    const second = newPythonTaskRunIdempotencyKey();

    expect(first).toMatch(/^[0-9a-f-]{36}$/);
    expect(second).not.toBe(first);
    expect(first.length).toBeLessThanOrEqual(200);
  });

  it("returns structured validation issues", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      valid: false,
      artifact_hash: "a".repeat(64),
      artifact_ref: null,
      detected_capabilities: [],
      imported_modules: [],
      issues: [{ code: "dynamic_code", path: "main.py", message: "blocked" }],
    }), { status: 200, headers: { "content-type": "application/json" } })));

    const result = await validatePythonTask(TASK);

    expect(result.valid).toBe(false);
    expect(result.issues[0]?.code).toBe("dynamic_code");
  });

  it("submits only artifact and target references for a governed run", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => new Response(
      JSON.stringify({
        submitted: true,
        correlation_id: "vm-task-correlation",
        action_type: "tool.run-python-on-vm",
        artifact_ref: "python-task:gpu.health-check@1.0.0#" + "a".repeat(64),
        target_resource_ref: "resource:compute/vm/gpu-worker",
      }),
      { status: 202, headers: { "content-type": "application/json" } },
    ));
    vi.stubGlobal("fetch", fetchMock);

    await requestPythonTaskRun({
      artifactRef: "python-task:gpu.health-check@1.0.0#" + "a".repeat(64),
      targetResourceRef: "resource:compute/vm/gpu-worker",
      reason: "Run the validated GPU health task.",
      idempotencyKey: "gpu-health-1",
    });

    const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body)) as Record<string, unknown>;
    expect(body["artifact_ref"]).toContain("python-task:gpu.health-check");
    expect(body["target_resource_ref"]).toBe("resource:compute/vm/gpu-worker");
    expect(JSON.stringify(body)).not.toContain("import torch");
  });
});
