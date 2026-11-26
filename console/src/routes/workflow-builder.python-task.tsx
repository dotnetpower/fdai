import { useRef, useState } from "preact/hooks";
import {
  CheckboxField,
  SelectField,
  TextInput,
  TextareaField,
} from "../components/form-controls";
import { CopyButton, StatusPill } from "../components/ui";
import {
  generatePythonTask,
  pythonTaskDraftKey,
  pythonTaskGenerationCanApply,
  requestPythonTaskRun,
  schedulePythonTask,
  stagePythonTask,
  testPythonTask,
  validatePythonTask,
  type PythonTaskAvailability,
  type PythonTaskCapability,
  type PythonTaskDraft,
  type PythonTaskFileDraft,
  type PythonTaskPlanResponse,
  type PythonTaskRunRequestResponse,
  type PythonTaskScheduleResponse,
  type PythonTaskValidation,
} from "../workflow/python-task";
import {
  identityForMutationIntent,
  type MutationIntentIdentity,
} from "../mutation-intent";
import { formatNumber, t } from "./i18n/workflow";

const CAPABILITIES: readonly PythonTaskCapability[] = [
  "gpu",
  "network",
  "filesystem_read",
  "filesystem_write",
];

const INITIAL_FILES: readonly PythonTaskFileDraft[] = [{
  path: "main.py",
  content: [
    "import json",
    "import torch",
    "",
    "result = {",
    "    \"cuda_available\": torch.cuda.is_available(),",
    "    \"device_count\": torch.cuda.device_count(),",
    "}",
    "print(json.dumps(result, sort_keys=True))",
    "",
  ].join("\n"),
}];

type Result = PythonTaskValidation | PythonTaskPlanResponse | PythonTaskRunRequestResponse | PythonTaskScheduleResponse;

interface StagedArtifact {
  readonly ref: string;
  readonly draftKey: string;
}

export function PythonTaskWorkbench({
  availability,
  onBack,
}: {
  readonly availability: PythonTaskAvailability;
  readonly onBack: () => void;
}) {
  const governedRunIntent = useRef<MutationIntentIdentity | null>(null);
  const draftRevision = useRef(0);
  const [files, setFiles] = useState<readonly PythonTaskFileDraft[]>(INITIAL_FILES);
  const [intent, setIntent] = useState("Write a Python task that reports CUDA availability and GPU count as JSON.");
  const [selectedPath, setSelectedPath] = useState("main.py");
  const [newPath, setNewPath] = useState("");
  const [taskId, setTaskId] = useState("gpu.health-check");
  const [version, setVersion] = useState("1.0.0");
  const [entrypoint, setEntrypoint] = useState("main.py");
  const [modules, setModules] = useState("torch");
  const [capabilities, setCapabilities] = useState<readonly PythonTaskCapability[]>(["gpu"]);
  const [timeoutSeconds, setTimeoutSeconds] = useState(300);
  const [target, setTarget] = useState("resource:compute/vm/gpu-worker");
  const [reason, setReason] = useState("Run the validated GPU health task.");
  const [cronExpression, setCronExpression] = useState("0 2 * * *");
  const [stagedArtifact, setStagedArtifact] = useState<StagedArtifact | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  const selected = files.find((file) => file.path === selectedPath) ?? files[0];

  const draft = (): PythonTaskDraft => ({
    task_id: taskId.trim(),
    version: version.trim(),
    entrypoint: entrypoint.trim(),
    files,
    required_modules: modules.split(",").map((value) => value.trim()).filter(Boolean),
    capabilities,
    timeout_seconds: timeoutSeconds,
    python_executable: "/usr/bin/python3",
  });
  const artifactRef = stagedArtifact?.draftKey === pythonTaskDraftKey(draft())
    ? stagedArtifact.ref
    : null;

  const run = async (
    action: string,
    operation: () => Promise<Result>,
    stagedDraftKey?: string,
  ) => {
    setBusy(action);
    setError(null);
    try {
      const next = await operation();
      setResult(next);
      if (
        "staged" in next
        && next.staged === true
        && typeof next.artifact_ref === "string"
        && stagedDraftKey !== undefined
      ) {
        setStagedArtifact({ ref: next.artifact_ref, draftKey: stagedDraftKey });
      }
      if ("submitted" in next && next.submitted) governedRunIntent.current = null;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  };

  const updateSelected = (content: string) => {
    draftRevision.current += 1;
    setFiles(files.map((file) => file.path === selected?.path ? { ...file, content } : file));
    setStagedArtifact(null);
  };

  const addFile = () => {
    const path = newPath.trim();
    if (!path || files.some((file) => file.path === path)) return;
    draftRevision.current += 1;
    setFiles([...files, { path, content: "" }]);
    setSelectedPath(path);
    setNewPath("");
    setStagedArtifact(null);
  };

  const removeSelected = () => {
    if (!selected || files.length === 1) return;
    draftRevision.current += 1;
    const remaining = files.filter((file) => file.path !== selected.path);
    setFiles(remaining);
    setSelectedPath(remaining[0]?.path ?? "");
    if (entrypoint === selected.path) setEntrypoint(remaining[0]?.path ?? "");
    setStagedArtifact(null);
  };

  const generate = async () => {
    const submittedRevision = draftRevision.current;
    setBusy("generate");
    setError(null);
    try {
      const generated = await generatePythonTask({
        intent: intent.trim(),
        taskIdHint: taskId.trim(),
        targetResourceRef: target.trim(),
        allowedModules: modules.split(",").map((value) => value.trim()).filter(Boolean),
      });
      if (!pythonTaskGenerationCanApply(draftRevision.current, submittedRevision)) {
        setError(t("workflow.pythonTask.discardedDraft"));
        return;
      }
      const task = generated.task;
      draftRevision.current += 1;
      setFiles(task.files);
      setSelectedPath(task.entrypoint);
      setTaskId(task.task_id);
      setVersion(task.version);
      setEntrypoint(task.entrypoint);
      setModules(task.required_modules.join(","));
      setCapabilities(task.capabilities);
      setTimeoutSeconds(task.timeout_seconds);
      setStagedArtifact(null);
      setResult(generated.validation);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section class="python-task-workbench">
      <header class="python-task-head">
        <div>
          <span class="eyebrow">{t("workflow.pythonTask.ontologyAction")}</span>
          <h3>{t("workflow.pythonTask.heading")}</h3>
        </div>
        <button type="button" class="btn btn-small" onClick={onBack}>{t("workflow.pythonTask.back")}</button>
      </header>

      <div class="python-task-layout">
        <section class="python-task-editor" aria-label={t("workflow.pythonTask.sourceFiles")}>
          <div class="python-task-filebar">
            <div class="python-task-tabs">
              {files.map((file) => (
                <button
                  key={file.path}
                  type="button"
                  class={file.path === selected?.path ? "is-active" : ""}
                  onClick={() => setSelectedPath(file.path)}
                >
                  {file.path}
                </button>
              ))}
            </div>
            <button type="button" class="btn btn-small" onClick={removeSelected} disabled={files.length === 1} aria-label={t("workflow.pythonTask.removeSelectedAria")}>{t("workflow.pythonTask.remove")}</button>
          </div>
          <TextareaField
            label={t("workflow.pythonTask.sourceFor", { path: selected?.path ?? t("workflow.pythonTask.taskFile") })}
            hideLabel
            mono
            rows={12}
            className="python-task-code"
            value={selected?.content ?? ""}
            onInput={updateSelected}
          />
          <div class="python-task-add-file">
            <TextInput
              label={t("workflow.pythonTask.newFilePath")}
              hideLabel
              mono
              value={newPath}
              placeholder="helpers.py"
              onInput={setNewPath}
            />
            <button type="button" class="btn btn-small" onClick={addFile}>{t("workflow.pythonTask.addFile")}</button>
          </div>
        </section>

        <aside class="python-task-manifest" aria-label={t("workflow.pythonTask.manifest")}>
          <TextInput
            label={t("workflow.pythonTask.field.taskId")}
            value={taskId}
            mono
            onInput={(next) => { draftRevision.current += 1; setTaskId(next); setStagedArtifact(null); }}
          />
          <TextInput
            label={t("workflow.pythonTask.field.version")}
            value={version}
            mono
            onInput={(next) => { draftRevision.current += 1; setVersion(next); setStagedArtifact(null); }}
          />
          <SelectField
            label={t("workflow.pythonTask.field.entrypoint")}
            value={entrypoint}
            options={files.filter((file) => file.path.endsWith(".py")).map((file) => ({
              value: file.path,
              label: file.path,
            }))}
            onChange={(next) => { draftRevision.current += 1; setEntrypoint(next); }}
          />
          <TextInput
            label={t("workflow.pythonTask.field.requiredModules")}
            value={modules}
            placeholder="torch,numpy"
            onInput={(next) => { draftRevision.current += 1; setModules(next); }}
          />
          <TextInput
            label={t("workflow.pythonTask.field.timeoutSeconds")}
            type="number"
            min="1"
            max="86400"
            value={String(timeoutSeconds)}
            onInput={(next) => { draftRevision.current += 1; setTimeoutSeconds(Number(next)); }}
          />
          <fieldset>
            <legend>{t("workflow.pythonTask.field.capabilities")}</legend>
            {CAPABILITIES.map((capability) => (
              <CheckboxField
                key={capability}
                label={capability.replaceAll("_", " ")}
                checked={capabilities.includes(capability)}
                className="python-task-check"
                onChange={() => {
                  draftRevision.current += 1;
                  setCapabilities(
                    capabilities.includes(capability)
                      ? capabilities.filter((value) => value !== capability)
                      : [...capabilities, capability],
                  );
                }}
              />
            ))}
          </fieldset>
          <TextInput
            label={t("workflow.pythonTask.field.targetResource")}
            value={target}
            onInput={setTarget}
          />
          <TextareaField
            label={t("workflow.pythonTask.field.runReason")}
            rows={3}
            value={reason}
            onInput={setReason}
          />
          <TextInput
            label={t("workflow.pythonTask.field.cronSchedule")}
            mono
            value={cronExpression}
            onInput={setCronExpression}
          />
        </aside>
      </div>

      <div class="python-task-intent">
        <TextareaField
          label={t("workflow.pythonTask.field.intent")}
          rows={2}
          value={intent}
          onInput={setIntent}
        />
        <button type="button" class="btn" disabled={busy !== null || !intent.trim() || !availability.operations.generate} onClick={() => void generate()}>{t(busy === "generate" ? "workflow.pythonTask.authoring" : "workflow.pythonTask.generate")}</button>
      </div>

      <div class="python-task-actions">
        <button type="button" class="btn" disabled={busy !== null || !availability.operations.validate} onClick={() => void run("validate", () => validatePythonTask(draft()))}>{t(busy === "validate" ? "workflow.pythonTask.validating" : "workflow.pythonTask.validate")}</button>
        <button type="button" class="btn" disabled={busy !== null || !availability.operations.stage} onClick={() => { const task = draft(); void run("stage", () => stagePythonTask(task), pythonTaskDraftKey(task)); }}>{t(busy === "stage" ? "workflow.pythonTask.staging" : "workflow.pythonTask.stage")}</button>
        <button type="button" class="btn" disabled={busy !== null || !target.trim() || !availability.operations.test} onClick={() => void run("test", () => testPythonTask(draft(), target.trim()))}>{t(busy === "test" ? "workflow.pythonTask.testing" : "workflow.pythonTask.test")}</button>
        <button type="button" class="btn primary" disabled={busy !== null || artifactRef === null || reason.trim().length < 10 || !availability.operations.request_run} onClick={() => { const request = { artifactRef: artifactRef ?? "", targetResourceRef: target.trim(), reason: reason.trim() }; const identity = identityForMutationIntent(governedRunIntent.current, JSON.stringify(request)); governedRunIntent.current = identity; void run("request", () => requestPythonTaskRun({ ...request, idempotencyKey: identity.idempotencyKey })); }}>{t(busy === "request" ? "workflow.pythonTask.submitting" : "workflow.pythonTask.request")}</button>
        <button type="button" class="btn" disabled={busy !== null || artifactRef === null || !cronExpression.trim() || !availability.operations.schedule} onClick={() => void run("schedule", () => schedulePythonTask({ artifactRef: artifactRef ?? "", targetResourceRef: target.trim(), workflowRef: "scheduled-gpu-python-task", cronExpression: cronExpression.trim() }))}>{t(busy === "schedule" ? "workflow.pythonTask.scheduling" : "workflow.pythonTask.createSchedule")}</button>
      </div>

      <PythonTaskResult result={result} error={error} artifactRef={artifactRef} />
    </section>
  );
}

function PythonTaskResult({ result, error, artifactRef }: { readonly result: Result | null; readonly error: string | null; readonly artifactRef: string | null }) {
  if (error) return <div class="state-block state-error" role="alert"><span class="state-icon">!</span><span>{error}</span></div>;
  if (!result) return <div class="python-task-result muted">{t("workflow.pythonTask.noResult")}</div>;
  if ("submitted" in result) {
    return <div class="python-task-result"><div><StatusPill kind="hil" label={t("workflow.pythonTask.submitted")} /><strong>{result.action_type}</strong></div><dl><div><dt>{t("workflow.pythonTask.field.correlation")}</dt><dd class="mono">{result.correlation_id}</dd></div><div><dt>{t("workflow.pythonTask.field.target")}</dt><dd class="mono">{result.target_resource_ref}</dd></div></dl></div>;
  }
  if ("scheduled" in result) {
    return <div class="python-task-result"><div><StatusPill kind="success" label={t("workflow.pythonTask.scheduled")} /><strong>{result.workflow_ref}</strong></div><dl><div><dt>{t("workflow.pythonTask.field.task")}</dt><dd class="mono">{result.task_id}</dd></div><div><dt>{t("workflow.pythonTask.field.cron")}</dt><dd class="mono">{result.cron_expression}</dd></div><div><dt>{t("workflow.pythonTask.field.event")}</dt><dd class="mono">{result.event_type}</dd></div><div><dt>{t("workflow.pythonTask.field.target")}</dt><dd class="mono">{result.target_resource_ref}</dd></div></dl></div>;
  }
  const plan = "plan" in result ? result.plan : null;
  return <div class="python-task-result"><div><StatusPill kind={result.valid ? "success" : "danger"} label={t(result.valid ? "workflow.pythonTask.valid" : "workflow.pythonTask.blocked")} />{artifactRef ? <CopyButton text={artifactRef} label={t("workflow.pythonTask.copyArtifact")} /> : null}</div>{result.issues.length > 0 ? <ul>{result.issues.map((issue) => <li key={`${issue.code}:${issue.path}`}><strong>{issue.code}</strong> <span class="mono">{issue.path}</span> - {issue.message}</li>)}</ul> : null}{plan ? <dl><div><dt>{t("workflow.pythonTask.field.status")}</dt><dd>{plan.status}</dd></div><div><dt>{t("workflow.pythonTask.field.files")}</dt><dd>{formatNumber(plan.files_would_copy)}</dd></div><div><dt>{t("workflow.pythonTask.field.bytes")}</dt><dd>{formatNumber(plan.bytes_would_copy)}</dd></div><div><dt>{t("workflow.pythonTask.field.targetCapabilities")}</dt><dd>{plan.target_capabilities.join(", ")}</dd></div></dl> : null}</div>;
}
