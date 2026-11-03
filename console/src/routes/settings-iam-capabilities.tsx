import { Tooltip } from "../components/tooltip";
import { settingsIamText as text } from "./settings-iam.i18n";

export function IamCapabilityDisclosure({ capabilities }: {
  readonly capabilities: readonly string[];
}) {
  return (
    <details>
      <summary>{text("capabilityCount", { count: capabilities.length })}</summary>
      <div class="settings-capability-chips">
        {capabilities.map((capability) => (
          <Tooltip key={capability} content={capability}>
            <span>{capabilityLabel(capability)} <code>{capability}</code></span>
          </Tooltip>
        ))}
      </div>
    </details>
  );
}

function capabilityLabel(capability: string): string {
  switch (capability) {
    case "view-console": return text("capabilityView");
    case "author-draft-pr": return text("capabilityDraft");
    case "manage-group-membership": return text("capabilityManage");
    case "trigger-kill-switch": return text("capabilityStop");
    default: return text("capabilityRegistered");
  }
}
