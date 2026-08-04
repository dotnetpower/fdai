import { useEffect, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable } from "../api";
import type { OperatorApiClient } from "../api";
import type { AuthContext } from "../auth";
import {
  PageHeader,
  type AsyncState,
} from "../components/ui";
import { t } from "../i18n";
import { AgentOversightBody } from "./agent-oversight-views";
import { PANTHEON } from "./agents.model";
import { panelArray, panelBoolean, panelContractError, panelNonEmptyString, panelNonNegativeInteger, panelNullableString, panelRecord, panelString, panelStringArray } from "./panel-decode";

/**
 * Handover panel. Fetches ``GET /stewardship`` and renders the handover map
 * (maintainers + 15 agents + their stewards) plus the coverage report
 * (bus-factor / over-assignment / maintainer findings) as read-only tables.
 *
 * Opt-in on the API side (``OperatorApiConfig.stewardship_map`` set). When not
 * wired, the panel surfaces a friendly "unavailable" state. Read-only: edits
 * are governance draft PRs, never a console mutation.
 */

type StewardKind = "user" | "group";
type StewardResponsibility = "accountable" | "informed";
type StewardDuty = "primary" | "backup" | "escalation";
type FindingSeverity = "warn" | "info";
type FindingCode =
  | "maintainer_single"
  | "autonomous_no_steward"
  | "duty_derived"
  | "backup_missing"
  | "bus_factor_one"
  | "over_assigned"
  | "stale_oid";
export type IdentityHealthStatus = "not_configured" | "pending" | "unavailable" | "clean" | "warn";

export interface StewardDto {
  readonly kind: StewardKind;
  readonly id: string;
  readonly responsibility: StewardResponsibility;
  readonly duty: StewardDuty | null;
}

export interface AgentStewardshipDto {
  readonly name: string;
  readonly autonomous: boolean;
  readonly accept_autonomous_reason: string | null;
  readonly bus_factor: number;
  readonly stewards: readonly StewardDto[];
}

export interface MapDto {
  readonly version: number;
  readonly maintainers: readonly string[];
  readonly maintainer_count: number;
  readonly hop_timeout_seconds: number;
  readonly over_assigned_max: number;
  readonly agents: readonly AgentStewardshipDto[];
}

export interface FindingDto {
  readonly code: FindingCode;
  readonly severity: FindingSeverity;
  readonly message: string;
  readonly agent: string | null;
}

export interface CoverageDto {
  readonly is_clean: boolean;
  readonly total_agents: number;
  readonly autonomous_agents: number;
  readonly maintainer_count: number;
  readonly findings: readonly FindingDto[];
}

export interface StewardshipResponse {
  readonly map: MapDto;
  readonly coverage: CoverageDto;
  readonly identity_health: {
    readonly status: IdentityHealthStatus;
    readonly checked_at: string | null;
    readonly finding_count: number | null;
  };
}

interface Props {
  readonly client: OperatorApiClient;
  readonly auth: AuthContext;
}

export function HandoverRoute({ client, auth }: Props) {
  const [state, setState] = useState<AsyncState<StewardshipResponse>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    (async () => {
      try {
        const data = decodeStewardship(await client.panel<unknown>("/stewardship"));
        if (!cancelled) {
          setState({ status: "ready", data });
        }
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : String(err);
          if (isOptionalOperatorApiUnavailable(err)) {
            setState({
              status: "unavailable",
              message: t("handover.unavailable"),
            });
          } else {
            setState({ status: "error", message });
          }
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client]);

  return (
    <div class="stack">
      <PageHeader
        title={t("route.handover")}
        subtitle={t("handover.subtitle")}
      />
      <AgentOversightBody stewardshipState={state} client={client} auth={auth} />
    </div>
  );
}

export function decodeStewardship(value: unknown): StewardshipResponse {
  const root = panelRecord(value, "stewardship");
  const map = panelRecord(root["map"], "stewardship.map");
  const coverage = panelRecord(root["coverage"], "stewardship.coverage");
  const identityHealth = panelRecord(root["identity_health"], "stewardship.identity_health");
  const identityHealthStatus = stewardshipEnum(
    identityHealth,
    "status",
    ["not_configured", "pending", "unavailable", "clean", "warn"],
  );
  const identityCheckedAt = panelNullableString(
    identityHealth,
    "checked_at",
    "stewardship.identity_health",
  );
  const identityFindingCount = identityHealth["finding_count"] === undefined
    ? null
    : panelNonNegativeInteger(identityHealth, "finding_count", "stewardship.identity_health");
  const version = panelNonNegativeInteger(map, "version", "stewardship.map");
  const hopTimeoutSeconds = panelNonNegativeInteger(map, "hop_timeout_seconds", "stewardship.map");
  const overAssignedMax = panelNonNegativeInteger(map, "over_assigned_max", "stewardship.map");
  if ((version !== 1 && version !== STEWARDSHIP_DUTY_VERSION) || hopTimeoutSeconds < 1 || overAssignedMax < 1) {
    throw panelContractError("stewardship map version, timeout, and assignment limit MUST be supported positive integers");
  }
  const decoded: StewardshipResponse = {
    map: {
      version,
      maintainers: panelStringArray(map["maintainers"], "stewardship.map.maintainers"),
      maintainer_count: panelNonNegativeInteger(map, "maintainer_count", "stewardship.map"),
      hop_timeout_seconds: hopTimeoutSeconds,
      over_assigned_max: overAssignedMax,
      agents: panelArray(map["agents"], "stewardship.map.agents").map((value, index) => {
        const agent = panelRecord(value, `stewardship.map.agents[${index}]`);
        return {
          name: panelString(agent, "name", "stewardship agent"),
          autonomous: panelBoolean(agent, "autonomous", "stewardship agent"),
          accept_autonomous_reason: panelNullableString(agent, "accept_autonomous_reason", "stewardship agent"),
          bus_factor: panelNonNegativeInteger(agent, "bus_factor", "stewardship agent"),
          stewards: panelArray(agent["stewards"], "stewardship agent.stewards").map((value, stewardIndex) => {
            const steward = panelRecord(value, `stewardship agent.stewards[${stewardIndex}]`);
            const responsibility = stewardshipEnum(
              steward,
              "responsibility",
              ["accountable", "informed"],
            );
            const rawDuty = steward["duty"];
            const duty = rawDuty === null || rawDuty === undefined
              ? null
              : stewardshipEnum(steward, "duty", ["primary", "backup", "escalation"]);
            return {
              kind: stewardshipEnum(steward, "kind", ["user", "group"]),
              id: panelNonEmptyString(steward, "id", "steward"),
              responsibility,
              duty,
            };
          }),
        };
      }),
    },
    coverage: {
      is_clean: panelBoolean(coverage, "is_clean", "stewardship.coverage"),
      total_agents: panelNonNegativeInteger(coverage, "total_agents", "stewardship.coverage"),
      autonomous_agents: panelNonNegativeInteger(coverage, "autonomous_agents", "stewardship.coverage"),
      maintainer_count: panelNonNegativeInteger(coverage, "maintainer_count", "stewardship.coverage"),
      findings: panelArray(coverage["findings"], "stewardship.coverage.findings").map((value, index) => {
        const finding = panelRecord(value, `stewardship.coverage.findings[${index}]`);
        return {
          code: stewardshipEnum(finding, "code", [
            "maintainer_single",
            "autonomous_no_steward",
            "duty_derived",
            "backup_missing",
            "bus_factor_one",
            "over_assigned",
            "stale_oid",
          ]),
          severity: stewardshipEnum(finding, "severity", ["warn", "info"]),
          message: panelString(finding, "message", "stewardship finding"),
          agent: panelNullableString(finding, "agent", "stewardship finding"),
        };
      }),
    },
    identity_health: {
      status: identityHealthStatus,
      checked_at: identityCheckedAt,
      finding_count: identityFindingCount,
    },
  };
  const expectedNames = PANTHEON.map((agent) => agent.name);
  const actualNames = decoded.map.agents.map((agent) => agent.name);
  if (
    actualNames.length !== expectedNames.length ||
    new Set(actualNames).size !== actualNames.length ||
    expectedNames.some((name) => !actualNames.includes(name))
  ) {
    throw panelContractError("stewardship.map.agents MUST contain the fixed 15-agent pantheon exactly once");
  }
  if (
    decoded.map.maintainer_count !== decoded.map.maintainers.length ||
    decoded.map.maintainer_count < 1 ||
    decoded.map.maintainers.some((maintainer) => maintainer.trim().length === 0) ||
    new Set(decoded.map.maintainers.filter((maintainer) => maintainer !== PLACEHOLDER_OID)).size !==
      decoded.map.maintainers.filter((maintainer) => maintainer !== PLACEHOLDER_OID).length
  ) {
    throw panelContractError("stewardship.map maintainers MUST satisfy the non-empty distinct maintainer floor");
  }
  for (const agent of decoded.map.agents) {
    const exactSubjects = agent.stewards.map((steward) => `${steward.kind}:${steward.id}`);
    if (new Set(exactSubjects).size !== exactSubjects.length) {
      throw panelContractError("stewardship agent stewards MUST contain distinct exact subjects");
    }
    const accountableUnits = new Set(
      agent.stewards
        .filter((steward) => steward.responsibility === "accountable")
        .map((steward) => `${steward.kind}:${steward.id}`),
    );
    if (agent.bus_factor !== accountableUnits.size) {
      throw panelContractError("stewardship agent.bus_factor MUST match distinct accountable subjects");
    }
    if (
      agent.autonomous !== (agent.accept_autonomous_reason !== null) ||
      agent.autonomous === (accountableUnits.size > 0) ||
      (agent.accept_autonomous_reason !== null && agent.accept_autonomous_reason.trim().length === 0)
    ) {
      throw panelContractError("stewardship agent autonomy MUST be an accountable-ownership alternative");
    }
    for (const steward of agent.stewards) {
      if (steward.responsibility === "informed" && steward.duty !== null) {
        throw panelContractError("informed stewardship entries MUST NOT declare duty");
      }
      if (
        decoded.map.version >= STEWARDSHIP_DUTY_VERSION &&
        steward.responsibility === "accountable" &&
        steward.duty === null
      ) {
        throw panelContractError("v2 accountable stewardship entries MUST declare duty");
      }
    }
    if (
      decoded.map.version >= STEWARDSHIP_DUTY_VERSION &&
      !agent.autonomous &&
      (
        !agent.stewards.some((steward) => steward.responsibility === "accountable" && steward.duty === "primary") ||
        !agent.stewards.some((steward) => steward.responsibility === "accountable" && (steward.duty === "backup" || steward.duty === "escalation"))
      )
    ) {
      throw panelContractError("stewardship v2 non-autonomous agents MUST include Primary and distinct Backup or Escalation coverage");
    }
  }
  if (
    decoded.coverage.total_agents !== decoded.map.agents.length ||
    decoded.coverage.maintainer_count !== decoded.map.maintainer_count ||
    decoded.coverage.autonomous_agents !== decoded.map.agents.filter((agent) => agent.autonomous).length
  ) {
    throw panelContractError("stewardship.coverage counts MUST match the handover map");
  }
  const pantheonNames = new Set(expectedNames);
  const findingSeverity: Readonly<Record<FindingCode, FindingSeverity>> = {
    maintainer_single: "warn",
    autonomous_no_steward: "info",
    duty_derived: "info",
    backup_missing: "warn",
    bus_factor_one: "warn",
    over_assigned: "warn",
    stale_oid: "warn",
  };
  const agentFindingCodes = new Set<FindingCode>([
    "autonomous_no_steward",
    "duty_derived",
    "backup_missing",
    "bus_factor_one",
  ]);
  const globalFindingCodes = new Set<FindingCode>(["maintainer_single", "over_assigned"]);
  if (
    decoded.coverage.findings.some((finding) => finding.agent !== null && !pantheonNames.has(finding.agent)) ||
    decoded.coverage.findings.some((finding) => finding.severity !== findingSeverity[finding.code]) ||
    decoded.coverage.findings.some((finding) => agentFindingCodes.has(finding.code) && finding.agent === null) ||
    decoded.coverage.findings.some((finding) => globalFindingCodes.has(finding.code) && finding.agent !== null) ||
    decoded.coverage.is_clean !== decoded.coverage.findings.every((finding) => finding.severity !== "warn")
  ) {
    throw panelContractError("stewardship.coverage findings MUST match canonical severity, scope, Pantheon references, and clean state");
  }
  const identityCheckCompleted = identityHealthStatus === "clean" || identityHealthStatus === "warn";
  const staleIdentityFindings = decoded.coverage.findings.filter((finding) => finding.code === "stale_oid").length;
  if (
    identityCheckCompleted !== (identityCheckedAt !== null) ||
    (identityCheckedAt !== null && !Number.isFinite(Date.parse(identityCheckedAt))) ||
    (identityCheckCompleted && identityFindingCount !== staleIdentityFindings) ||
    (!identityCheckCompleted && identityFindingCount !== null) ||
    (identityHealthStatus === "clean" && staleIdentityFindings !== 0) ||
    (identityHealthStatus === "warn" && staleIdentityFindings === 0)
  ) {
    throw panelContractError("stewardship.identity_health MUST match its completed check evidence");
  }
  return decoded;
}

function stewardshipEnum<const T extends string>(
  value: Readonly<Record<string, unknown>>,
  key: string,
  allowed: readonly T[],
): T {
  const decoded = panelString(value, key, "stewardship");
  if (!allowed.includes(decoded as T)) {
    throw panelContractError(`stewardship.${key} MUST be one of ${allowed.join(", ")}`);
  }
  return decoded as T;
}

const STEWARDSHIP_DUTY_VERSION = 2;
const PLACEHOLDER_OID = "00000000-0000-0000-0000-000000000000";
