import {
  panelArray, panelBoolean, panelContractError, panelNonEmptyString,
  panelNonNegativeInteger, panelRecord,
} from "./panel-decode";

export interface GithubSource {
  readonly repository_alias: string;
  readonly location: string;
  readonly revision: number;
  readonly enabled: boolean;
  readonly knowledge_source: {
    readonly knowledge_read_enabled: boolean;
    readonly credential_reference: "public" | "deployment-github-app";
    readonly observed_commit: string;
    readonly readme_digest: string;
    readonly observed_at: string;
  } | null;
}

export interface GithubSources {
  readonly sources: readonly GithubSource[];
  readonly gaps: readonly string[];
}

export function decodeGithubSources(value: unknown): GithubSources {
  const root = panelRecord(value, "GitHub knowledge sources");
  if (root.indexed !== false) throw panelContractError("GitHub source is not indexing evidence");
  return {
    sources: panelArray(root.sources, "GitHub sources").map((value) => {
      const row = panelRecord(value, "GitHub source");
      const revision = panelNonNegativeInteger(row, "revision", "GitHub source");
      if (revision < 1) throw panelContractError("GitHub source revision is invalid");
      let source: GithubSource["knowledge_source"] = null;
      if (row.knowledge_source !== null) {
        const record = panelRecord(row.knowledge_source, "GitHub observation");
        const reference = record.credential_reference;
        if (reference !== "public" && reference !== "deployment-github-app") {
          throw panelContractError("GitHub credential reference is invalid");
        }
        const commit = panelNonEmptyString(record, "observed_commit", "GitHub observation");
        const digest = panelNonEmptyString(record, "readme_digest", "GitHub observation");
        const time = panelNonEmptyString(record, "observed_at", "GitHub observation");
        if (!/^[0-9a-f]{40}$/.test(commit) || !/^[0-9a-f]{64}$/.test(digest) || !Number.isFinite(Date.parse(time))) {
          throw panelContractError("GitHub provenance is invalid");
        }
        source = {
          credential_reference: reference,
          knowledge_read_enabled: panelBoolean(record, "knowledge_read_enabled", "GitHub observation"),
          observed_commit: commit, readme_digest: digest, observed_at: time,
        };
      }
      return {
        repository_alias: panelNonEmptyString(row, "repository_alias", "GitHub source"),
        location: panelNonEmptyString(row, "location", "GitHub source"),
        revision, enabled: panelBoolean(row, "enabled", "GitHub source"), knowledge_source: source,
      };
    }),
    gaps: panelArray(root.gaps, "GitHub gaps").map((value) =>
      panelNonEmptyString(panelRecord(value, "GitHub gap"), "reason_code", "GitHub gap")),
  };
}

export function githubConnectionInputValid(alias: string, location: string): boolean {
  return /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(alias)
    && /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\/[A-Za-z0-9._-]{1,100}$/.test(location)
    && ![".", ".."].includes(location.split("/")[1] ?? "");
}
