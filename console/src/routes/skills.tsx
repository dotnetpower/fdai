import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import {
  AsyncBoundary,
  DataTable,
  EmptyState,
  KpiCard,
  KpiGrid,
  PageHeader,
  StatusPill,
  type AsyncState,
  type Column,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import {
  panelArray,
  panelBoolean,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelRecord,
  panelStringArray,
} from "./panel-decode";

interface SkillReference {
  readonly path: string;
  readonly sha256: string;
  readonly size_bytes: number;
  readonly media_type: string;
}

interface RuntimeSkillItem {
  readonly name: string;
  readonly version: string;
  readonly description: string;
  readonly source: string;
  readonly enabled: boolean;
  readonly required_tools: readonly string[];
  readonly missing_tools: readonly string[];
  readonly allowed_agents: readonly string[];
  readonly agent_eligible: boolean;
  readonly eligible: boolean;
  readonly eligibility_reason: string;
  readonly body_sha256: string;
  readonly references: readonly SkillReference[];
}

interface SkillDiagnostic {
  readonly operation: string;
  readonly name: string | null;
  readonly reference: string | null;
  readonly status: string;
  readonly reason: string;
  readonly digests: Readonly<Record<string, string>>;
}

interface RuntimeSkillBundleMember {
  readonly name: string;
  readonly version: string;
}

interface RuntimeSkillBundleItem {
  readonly name: string;
  readonly version: string;
  readonly description: string;
  readonly source: string;
  readonly digest: string;
  readonly enabled: boolean;
  readonly members: readonly RuntimeSkillBundleMember[];
  readonly required_tools: readonly string[];
  readonly missing_tools: readonly string[];
  readonly allowed_agents: readonly string[];
  readonly agent_eligible: boolean;
  readonly compatible: boolean;
  readonly missing_members: readonly string[];
  readonly disabled_members: readonly string[];
  readonly incompatible_members: readonly string[];
  readonly trust_status: string;
  readonly eligible: boolean;
}

export interface RuntimeSkillsResponse {
  readonly source: string;
  readonly execution_eligibility: boolean;
  readonly trust_rechecked_on_load: boolean;
  readonly agent: string;
  readonly available_tools: readonly string[];
  readonly installed_count: number;
  readonly eligible_count: number;
  readonly skills: readonly RuntimeSkillItem[];
  readonly installed_bundle_count: number;
  readonly eligible_bundle_count: number;
  readonly bundles: readonly RuntimeSkillBundleItem[];
  readonly diagnostics: readonly SkillDiagnostic[];
  readonly mutation_controls: boolean;
}

export function SkillsRoute({ client }: { readonly client: ReadApiClient }) {
  const [state, setState] = useState<AsyncState<RuntimeSkillsResponse>>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    client.panel<unknown>("/skills")
      .then((value) => {
        if (!cancelled) setState({ status: "ready", data: decodeRuntimeSkills(value) });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({
            status: "error",
            message: error instanceof Error ? error.message : String(error),
          });
        }
      });
    return () => { cancelled = true; };
  }, [client]);
  return (
    <div class="stack skills-route">
      <PageHeader title={t("route.skills")} subtitle={t("nav.panelSub.skills")} />
      <AsyncBoundary state={state} resourceLabel="runtime skills">
        {(data) => <SkillsBody data={data} />}
      </AsyncBoundary>
    </div>
  );
}

export function decodeRuntimeSkills(value: unknown): RuntimeSkillsResponse {
  const root = panelRecord(value, "skills");
  const skills = panelArray(root["skills"], "skills.items").map(decodeSkill);
  const diagnostics = panelArray(root["diagnostics"], "skills.diagnostics")
    .map(decodeDiagnostic);
  const bundles = panelArray(root["bundles"], "skills.bundles").map(decodeBundle);
  const installedCount = panelNonNegativeInteger(root, "installed_count", "skills");
  const eligibleCount = panelNonNegativeInteger(root, "eligible_count", "skills");
  const installedBundleCount = panelNonNegativeInteger(root, "installed_bundle_count", "skills");
  const eligibleBundleCount = panelNonNegativeInteger(root, "eligible_bundle_count", "skills");
  if (installedCount !== skills.length) {
    throw new Error("invalid read API response: skills.installed_count MUST match items");
  }
  if (eligibleCount !== skills.filter((item) => item.eligible).length) {
    throw new Error("invalid read API response: skills.eligible_count MUST match eligible items");
  }
  const names = skills.map((item) => item.name);
  if (new Set(names).size !== names.length) {
    throw new Error("invalid read API response: skill names MUST be unique");
  }
  if (installedBundleCount !== bundles.length) {
    throw new Error("invalid read API response: skills.installed_bundle_count MUST match bundles");
  }
  if (eligibleBundleCount !== bundles.filter((item) => item.eligible).length) {
    throw new Error("invalid read API response: skills.eligible_bundle_count MUST match eligible bundles");
  }
  const bundleNames = bundles.map((item) => item.name);
  if (new Set(bundleNames).size !== bundleNames.length) {
    throw new Error("invalid read API response: skill bundle names MUST be unique");
  }
  return {
    source: panelNonEmptyString(root, "source", "skills"),
    execution_eligibility: panelBoolean(root, "execution_eligibility", "skills"),
    trust_rechecked_on_load: panelBoolean(root, "trust_rechecked_on_load", "skills"),
    agent: panelNonEmptyString(root, "agent", "skills"),
    available_tools: panelStringArray(root["available_tools"], "skills.available_tools"),
    installed_count: installedCount,
    eligible_count: eligibleCount,
    skills,
    installed_bundle_count: installedBundleCount,
    eligible_bundle_count: eligibleBundleCount,
    bundles,
    diagnostics,
    mutation_controls: panelBoolean(root, "mutation_controls", "skills"),
  };
}

function decodeBundle(value: unknown, index: number): RuntimeSkillBundleItem {
  const label = `skills.bundles[${index}]`;
  const item = panelRecord(value, label);
  return {
    name: panelNonEmptyString(item, "name", label),
    version: panelNonEmptyString(item, "version", label),
    description: panelNonEmptyString(item, "description", label),
    source: panelNonEmptyString(item, "source", label),
    digest: panelNonEmptyString(item, "digest", label),
    enabled: panelBoolean(item, "enabled", label),
    members: panelArray(item["members"], `${label}.members`).map((raw, memberIndex) => {
      const memberLabel = `${label}.members[${memberIndex}]`;
      const member = panelRecord(raw, memberLabel);
      return {
        name: panelNonEmptyString(member, "name", memberLabel),
        version: panelNonEmptyString(member, "version", memberLabel),
      };
    }),
    required_tools: panelStringArray(item["required_tools"], `${label}.required_tools`),
    missing_tools: panelStringArray(item["missing_tools"], `${label}.missing_tools`),
    allowed_agents: panelStringArray(item["allowed_agents"], `${label}.allowed_agents`),
    agent_eligible: panelBoolean(item, "agent_eligible", label),
    compatible: panelBoolean(item, "compatible", label),
    missing_members: panelStringArray(item["missing_members"], `${label}.missing_members`),
    disabled_members: panelStringArray(item["disabled_members"], `${label}.disabled_members`),
    incompatible_members: panelStringArray(
      item["incompatible_members"],
      `${label}.incompatible_members`,
    ),
    trust_status: panelNonEmptyString(item, "trust_status", label),
    eligible: panelBoolean(item, "eligible", label),
  };
}

function decodeSkill(value: unknown, index: number): RuntimeSkillItem {
  const label = `skills.items[${index}]`;
  const item = panelRecord(value, label);
  return {
    name: panelNonEmptyString(item, "name", label),
    version: panelNonEmptyString(item, "version", label),
    description: panelNonEmptyString(item, "description", label),
    source: panelNonEmptyString(item, "source", label),
    enabled: panelBoolean(item, "enabled", label),
    required_tools: panelStringArray(item["required_tools"], `${label}.required_tools`),
    missing_tools: panelStringArray(item["missing_tools"], `${label}.missing_tools`),
    allowed_agents: panelStringArray(item["allowed_agents"], `${label}.allowed_agents`),
    agent_eligible: panelBoolean(item, "agent_eligible", label),
    eligible: panelBoolean(item, "eligible", label),
    eligibility_reason: panelNonEmptyString(item, "eligibility_reason", label),
    body_sha256: panelNonEmptyString(item, "body_sha256", label),
    references: panelArray(item["references"], `${label}.references`).map((raw, refIndex) => {
      const refLabel = `${label}.references[${refIndex}]`;
      const reference = panelRecord(raw, refLabel);
      return {
        path: panelNonEmptyString(reference, "path", refLabel),
        sha256: panelNonEmptyString(reference, "sha256", refLabel),
        size_bytes: panelNonNegativeInteger(reference, "size_bytes", refLabel),
        media_type: panelNonEmptyString(reference, "media_type", refLabel),
      };
    }),
  };
}

function decodeDiagnostic(value: unknown, index: number): SkillDiagnostic {
  const label = `skills.diagnostics[${index}]`;
  const item = panelRecord(value, label);
  const digests = panelRecord(item["digests"], `${label}.digests`);
  if (!Object.values(digests).every((digest) => typeof digest === "string")) {
    throw new Error(`invalid read API response: ${label}.digests MUST contain strings`);
  }
  return {
    operation: panelNonEmptyString(item, "operation", label),
    name: nullableString(item["name"], `${label}.name`),
    reference: nullableString(item["reference"], `${label}.reference`),
    status: panelNonEmptyString(item, "status", label),
    reason: panelNonEmptyString(item, "reason", label),
    digests: digests as Readonly<Record<string, string>>,
  };
}

function nullableString(value: unknown, label: string): string | null {
  if (value === null) return null;
  if (typeof value !== "string") {
    throw new Error(`invalid read API response: ${label} MUST be a string or null`);
  }
  return value;
}

const skillColumns: readonly Column<RuntimeSkillItem>[] = [
  { key: "name", header: "Skill", render: (item) => <div><strong>{item.name}</strong><small>{item.description}</small></div> },
  { key: "version", header: "Version", render: (item) => <code>{item.version}</code> },
  { key: "source", header: "Publisher", render: (item) => item.source },
  { key: "dependencies", header: "Required tools", render: (item) => item.required_tools.join(", ") || "None" },
  { key: "agents", header: "Allowed agents", render: (item) => item.allowed_agents.join(", ") || "All" },
  { key: "references", header: "References", render: (item) => item.references.length },
  {
    key: "eligibility",
    header: "Load eligibility",
    render: (item) => (
      <StatusPill
        kind={item.eligible ? "success" : item.enabled ? "warning" : "shadow"}
        label={item.eligible ? "Eligible" : item.eligibility_reason}
      />
    ),
  },
];

const diagnosticColumns: readonly Column<SkillDiagnostic>[] = [
  { key: "operation", header: "Operation", render: (item) => item.operation },
  { key: "skill", header: "Skill / reference", render: (item) => [item.name, item.reference].filter(Boolean).join(" / ") || "-" },
  { key: "status", header: "Status", render: (item) => <StatusPill kind={item.status === "selected" ? "success" : "warning"} label={item.status} /> },
  { key: "reason", header: "Reason", render: (item) => item.reason },
  { key: "digests", header: "Verified digests", render: (item) => Object.keys(item.digests).length },
];

const bundleColumns: readonly Column<RuntimeSkillBundleItem>[] = [
  { key: "name", header: "Bundle", render: (item) => <div><strong>{item.name}</strong><small>{item.description}</small></div> },
  { key: "version", header: "Version", render: (item) => <code>{item.version}</code> },
  { key: "members", header: "Ordered members", render: (item) => item.members.map((member) => `${member.name} ${member.version}`).join(", ") },
  { key: "tools", header: "Required tools", render: (item) => item.required_tools.join(", ") || "None" },
  { key: "trust", header: "Trust", render: (item) => item.trust_status },
  {
    key: "compatibility",
    header: "Compatibility",
    render: (item) => <StatusPill kind={item.compatible ? "success" : "warning"} label={item.compatible ? "Compatible" : "Blocked"} />,
  },
  {
    key: "eligibility",
    header: "Load eligibility",
    render: (item) => <StatusPill kind={item.eligible ? "success" : item.enabled ? "warning" : "shadow"} label={item.eligible ? "Eligible" : item.enabled ? "Blocked" : "Disabled"} />,
  },
];

function SkillsBody({ data }: { readonly data: RuntimeSkillsResponse }) {
  usePublishViewContext(
    () => ({
      routeId: "skills",
      routeLabel: "Skills",
      purpose: "Read-only inspection of installed runtime skill metadata, dependencies, eligibility, and bounded load diagnostics.",
      glossary: composeGlossary([], [{
        term: "runtime skill",
        plain: "reviewed instructions for using tools that are already registered",
        tech: "RuntimeSkill",
      }]),
      headline: `${data.installed_count} skills and ${data.installed_bundle_count} bundles installed for ${data.agent}`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "source", value: data.source, group: "provenance" },
        { key: "installed_count", value: data.installed_count, group: "skills" },
        { key: "eligible_count", value: data.eligible_count, group: "skills" },
        { key: "installed_bundle_count", value: data.installed_bundle_count, group: "bundles" },
        { key: "eligible_bundle_count", value: data.eligible_bundle_count, group: "bundles" },
        { key: "execution_eligibility", value: data.execution_eligibility, group: "safety" },
        { key: "mutation_controls", value: data.mutation_controls, group: "safety" },
      ],
      records: {
        skills: data.skills.map((item) => ({ ...item })),
        bundles: data.bundles.map((item) => ({ ...item })),
        diagnostics: data.diagnostics.map((item) => ({ ...item })),
      },
    }),
    [data],
  );
  return (
    <div class="stack">
      <div class="governance-readonly-banner">
        <strong>Inspection only.</strong>
        <span>Loading rechecks trust and returns complete artifacts. This console cannot install, enable, approve, or execute a skill.</span>
      </div>
      <KpiGrid>
        <KpiCard label="Installed" value={data.installed_count.toLocaleString()} />
        <KpiCard label="Eligible" value={data.eligible_count.toLocaleString()} />
        <KpiCard label="Bundles" value={data.installed_bundle_count.toLocaleString()} />
        <KpiCard label="Eligible bundles" value={data.eligible_bundle_count.toLocaleString()} />
        <KpiCard label="Diagnostics" value={data.diagnostics.length.toLocaleString()} />
      </KpiGrid>
      <section class="stack-section" aria-label="Installed skill index">
        <header class="section-header"><div><h3>Installed index</h3><p>Metadata and dependency checks for {data.agent}</p></div></header>
        <DataTable rows={data.skills} columns={skillColumns} keyOf={(item) => item.name} empty={<EmptyState title="No runtime skills installed" />} />
      </section>
      <section class="stack-section" aria-label="Governed skill bundle index">
        <header class="section-header"><div><h3>Governed bundles</h3><p>Ordered reviewed skill sets with exact versions and effective compatibility</p></div></header>
        <DataTable rows={data.bundles} columns={bundleColumns} keyOf={(item) => item.name} empty={<EmptyState title="No governed skill bundles installed" />} />
      </section>
      <section class="stack-section" aria-label="Skill load diagnostics">
        <header class="section-header"><div><h3>Load diagnostics</h3><p>Bounded outcomes only. Skill bodies and reference content are never retained here.</p></div></header>
        <DataTable rows={data.diagnostics} columns={diagnosticColumns} keyOf={(item, index) => `${index}:${item.operation}:${item.name ?? "none"}`} empty={<EmptyState title="No skill reads recorded" />} />
      </section>
    </div>
  );
}
