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
import { panelArray, panelBoolean, panelContractError, panelNullableString, panelNumber, panelRecord, panelString, panelStringArray } from "./panel-decode";

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
  readonly code: string;
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
    : panelNumber(identityHealth, "finding_count", "stewardship.identity_health");
  const decoded: StewardshipResponse = {
    map: {
      version: panelNumber(map, "version", "stewardship.map"),
      maintainers: panelStringArray(map["maintainers"], "stewardship.map.maintainers"),
      maintainer_count: panelNumber(map, "maintainer_count", "stewardship.map"),
      hop_timeout_seconds: panelNumber(map, "hop_timeout_seconds", "stewardship.map"),
      over_assigned_max: panelNumber(map, "over_assigned_max", "stewardship.map"),
      agents: panelArray(map["agents"], "stewardship.map.agents").map((value, index) => {
        const agent = panelRecord(value, `stewardship.map.agents[${index}]`);
        return {
          name: panelString(agent, "name", "stewardship agent"),
          autonomous: panelBoolean(agent, "autonomous", "stewardship agent"),
          accept_autonomous_reason: panelNullableString(agent, "accept_autonomous_reason", "stewardship agent"),
          bus_factor: panelNumber(agent, "bus_factor", "stewardship agent"),
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
              id: panelString(steward, "id", "steward"),
              responsibility,
              duty,
            };
          }),
        };
      }),
    },
    coverage: {
      is_clean: panelBoolean(coverage, "is_clean", "stewardship.coverage"),
      total_agents: panelNumber(coverage, "total_agents", "stewardship.coverage"),
      autonomous_agents: panelNumber(coverage, "autonomous_agents", "stewardship.coverage"),
      maintainer_count: panelNumber(coverage, "maintainer_count", "stewardship.coverage"),
      findings: panelArray(coverage["findings"], "stewardship.coverage.findings").map((value, index) => {
        const finding = panelRecord(value, `stewardship.coverage.findings[${index}]`);
        return {
          code: panelString(finding, "code", "stewardship finding"),
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
  if (decoded.map.maintainer_count !== decoded.map.maintainers.length) {
    throw panelContractError("stewardship.map.maintainer_count MUST match maintainers.length");
  }
  for (const agent of decoded.map.agents) {
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
      agent.autonomous === (accountableUnits.size > 0)
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
  }
  if (
    decoded.coverage.total_agents !== decoded.map.agents.length ||
    decoded.coverage.maintainer_count !== decoded.map.maintainer_count ||
    decoded.coverage.autonomous_agents !== decoded.map.agents.filter((agent) => agent.autonomous).length
  ) {
    throw panelContractError("stewardship.coverage counts MUST match the handover map");
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
