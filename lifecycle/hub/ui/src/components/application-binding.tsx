import { useRef, useState } from "preact/hooks";
import { hubApi, HubApiError, type ExecutionSettings } from "../api";
import { useAsync } from "../hooks/use-async";
import { AsyncBoundary } from "./async-boundary";

type Props = { installationId: string; blocked: boolean; onSaved: () => void };

export function ApplicationBindingPanel(props: Props) {
  const state = useAsync(
    () => hubApi.getExecutionSettings(props.installationId), [props.installationId],
  );
  return <section aria-label="Application binding">
    <h2 class="panel-title">Application binding</h2>
    <p class="note">Choose the application this installation may deploy. This binding is permanent.
      It does not grant ownership, change Agent policy, compute a Plan, or deploy anything.</p>
    <AsyncBoundary state={state}>
      {current => <BindingForm {...props} current={current} reload={state.reload} />}
    </AsyncBoundary>
  </section>;
}

function BindingForm({
  installationId, blocked, onSaved, current, reload,
}: Props & { current: ExecutionSettings; reload: () => void }) {
  const [product, setProduct] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  if (current.product === undefined) {
    return <p class="banner" role="status">This Hub does not report application bindings.
      No binding change is available.</p>;
  }
  if (current.product !== null) {
    return <p class="banner" role="status">Bound application: <strong>{current.product}</strong>.
      The installation-local Agent policy must independently match this application.</p>;
  }
  const valid = /^[a-z][a-z0-9-]{0,62}$/.test(product);
  const disabled = busy || blocked || error !== "";

  async function save() {
    if (inFlight.current || disabled || !valid || confirmation !== product) return;
    inFlight.current = true;
    setBusy(true);
    try {
      await hubApi.bindApplication(installationId, {
        request_id: crypto.randomUUID(),
        expected_settings_digest: current.settings_digest,
        product,
        reason_code: "operator_application_binding",
        confirmation: `bind application ${installationId} ${product} ${current.settings_digest}`,
      });
      onSaved();
    } catch (failure: unknown) {
      setError(failure instanceof HubApiError
        ? `The Hub rejected this binding (${failure.reasonCode}). Refresh before trying again.`
        : "The binding outcome could not be confirmed. Refresh before another request. No automatic retry was made.");
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return <form class="execution-settings" onSubmit={event => {
    event.preventDefault();
    void save();
  }}>
    {blocked && <p class="banner" role="status">An open Plan blocks application binding.
      Resolve the existing Plan, then refresh this installation.</p>}
    {error && <p class="banner fail" role="alert">{error}</p>}
    <fieldset class="execution-fields" disabled={disabled}>
      <legend>Bind reviewed application</legend>
      <p class="note">Enter the product identifier from the reviewed release package.
        Without a binding, this installation accepts only legacy runtime packages.</p>
      <label class="execution-field">Application ID
        <input class="input" required pattern="[a-z][a-z0-9-]{0,62}" maxLength={63}
          value={product} onInput={event => {
            setProduct(event.currentTarget.value);
            setConfirmation("");
          }} />
      </label>
      <label class="execution-field">Type the application ID again to confirm
        <input class="input" required maxLength={63} autoComplete="off"
          value={confirmation} onInput={event => setConfirmation(event.currentTarget.value)} />
      </label>
      <button class="btn primary" type="submit" disabled={!valid || confirmation !== product}>
        {busy ? "Binding application..." : "Bind application"}
      </button>
    </fieldset>
    <button class="btn" type="button" disabled={busy} onClick={reload}>Refresh binding</button>
  </form>;
}
