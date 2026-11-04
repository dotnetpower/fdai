import { useRef, useState } from "preact/hooks";
import { hubApi, HubApiError, type ExecutionSettings } from "../api";
import { useAsync } from "../hooks/use-async";
import { tr, useHubLocale } from "../locale";
import { AsyncBoundary } from "./async-boundary";
import { useEntraSession } from "./nav";

type Props = { installationId: string; blocked: boolean; onSaved: () => void };

export function ApplicationBindingPanel(props: Props) {
  const [locale] = useHubLocale();
  const entraSession = useEntraSession();
  const state = useAsync(
    () => hubApi.getExecutionSettings(props.installationId),
    [props.installationId, entraSession?.authenticated ?? false, entraSession?.actor ?? ""],
  );
  return <section aria-label={tr(locale, "Application binding", "애플리케이션 바인딩")}>
    <h2 class="panel-title">{tr(locale, "Application binding", "애플리케이션 바인딩")}</h2>
    <p class="note">{tr(
      locale,
      "Choose the application this installation may deploy. This binding is permanent. It does not grant ownership, change Agent policy, compute a Plan, or deploy anything.",
      "이 설치 환경에서 배포할 수 있는 애플리케이션을 지정합니다. 바인딩은 영구적이며, 소유권 부여, 에이전트 정책 변경, 계획 계산 또는 배포를 직접 수행하지 않습니다.",
    )}</p>
    <AsyncBoundary state={state}>
      {current => <BindingForm {...props} current={current} reload={state.reload} />}
    </AsyncBoundary>
  </section>;
}

function BindingForm({
  installationId, blocked, onSaved, current, reload,
}: Props & { current: ExecutionSettings; reload: () => void }) {
  const [locale] = useHubLocale();
  const [product, setProduct] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  if (current.product === undefined) {
    return <p class="banner" role="status">{tr(
      locale,
      "This Hub does not report application bindings. No binding change is available.",
      "이 Hub는 애플리케이션 바인딩 정보를 보고하지 않습니다. 바인딩 변경을 사용할 수 없습니다.",
    )}</p>;
  }
  if (current.product !== null) {
    return <p class="banner" role="status">
      {tr(locale, "Bound application:", "바인딩된 애플리케이션:")} <strong>{current.product}</strong>.{" "}
      {tr(
        locale,
        "The installation-local Agent policy must independently match this application.",
        "설치 환경의 로컬 에이전트 정책도 이 애플리케이션과 독립적으로 일치해야 합니다.",
      )}
    </p>;
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
        ? tr(
            locale,
            `The Hub rejected this binding (${failure.reasonCode}). Refresh before trying again.`,
            `Hub가 이 바인딩 요청을 거부했습니다 (${failure.reasonCode}). 새로 고침한 뒤 다시 시도하세요.`,
          )
        : tr(
            locale,
            "The binding outcome could not be confirmed. Refresh before another request. No automatic retry was made.",
            "바인딩 결과를 확인할 수 없습니다. 새로 고침한 뒤 다시 요청하세요. 자동 재시도는 수행하지 않았습니다.",
          ));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return <form class="execution-settings" onSubmit={event => {
    event.preventDefault();
    void save();
  }}>
    {blocked && <p class="banner" role="status">{tr(
      locale,
      "An open Plan blocks application binding. Resolve the existing Plan, then refresh this installation.",
      "열린 계획이 있어 애플리케이션 바인딩이 차단되었습니다. 기존 계획을 해결한 뒤 이 설치 환경을 새로 고침하세요.",
    )}</p>}
    {error && <p class="banner fail" role="alert">{error}</p>}
    <fieldset class="execution-fields" disabled={disabled}>
      <legend>{tr(locale, "Bind reviewed application", "검토된 애플리케이션 바인딩")}</legend>
      <p class="note">{tr(
        locale,
        "Enter the product identifier from the reviewed release package. Without a binding, this installation accepts only legacy runtime packages.",
        "검토된 릴리스 패키지의 제품 식별자를 입력하세요. 바인딩이 없으면 이 설치 환경은 기존 런타임 패키지만 허용합니다.",
      )}</p>
      <label class="execution-field">{tr(locale, "Application ID", "애플리케이션 ID")}
        <input class="input" required pattern="[a-z][a-z0-9-]{0,62}" maxLength={63}
          value={product} onInput={event => {
            setProduct(event.currentTarget.value);
            setConfirmation("");
          }} />
      </label>
      <label class="execution-field">{tr(
        locale,
        "Type the application ID again to confirm",
        "확인을 위해 애플리케이션 ID를 다시 입력하세요",
      )}
        <input class="input" required maxLength={63} autoComplete="off"
          value={confirmation} onInput={event => setConfirmation(event.currentTarget.value)} />
      </label>
      <button class="btn primary" type="submit" disabled={!valid || confirmation !== product}>
        {busy
          ? tr(locale, "Binding application...", "애플리케이션 바인딩 중...")
          : tr(locale, "Bind application", "애플리케이션 바인딩")}
      </button>
    </fieldset>
    <button class="btn" type="button" disabled={busy} onClick={reload}>
      {tr(locale, "Refresh binding", "바인딩 새로 고침")}
    </button>
  </form>;
}
