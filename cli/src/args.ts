export type Surface = "cli" | "text" | "slack" | "teams";
export type Source = "sample" | "api";
export type BriefingMode = "needs-me" | "all-clear";
export type CliLocale = "en" | "ko";

export interface CliOptions {
  surface: Surface;
  source: Source;
  mode: BriefingMode;
  locale: CliLocale;
  apiUrl: string;
}

const DEFAULTS: CliOptions = {
  surface: "cli",
  source: "sample",
  mode: "needs-me",
  locale: "en",
  apiUrl: "http://127.0.0.1:8010",
};

export const CLI_HELP = `Usage: fdai-console [options]

Options:
  --surface <cli|text|slack|teams>   Output surface (default: cli)
  --source <sample|api>              Data source (default: sample)
  --mode <needs-me|all-clear>        Sample fixture state (default: needs-me)
  --locale <en|ko>                   Presentation locale (default: FDAI_LOCALE or en)
  --api <http(s)://host[:port]>      Shared Operator API base URL
  -h, --help                         Show this help

Interactive questions require --source=api and are delegated to POST /chat.
`;

export function isHelpRequest(argv: readonly string[]): boolean {
  return argv.includes("--help") || argv.includes("-h");
}

export function parseCliArgs(
  argv: readonly string[],
  env: Readonly<Record<string, string | undefined>> = process.env,
): CliOptions {
  const values: Record<string, string> = {};
  const allowed = new Set(["surface", "source", "mode", "locale", "api"]);
  for (let index = 0; index < argv.length; index++) {
    const arg = argv[index]!;
    if (!arg.startsWith("--")) {
      throw new Error(`invalid argument ${JSON.stringify(arg)}; expected --name value`);
    }
    if (arg.includes("=")) {
      const [name, ...rest] = arg.slice(2).split("=");
      recordOption(values, allowed, name!, rest.join("="));
      continue;
    }
    const name = arg.slice(2);
    const value = argv[index + 1];
    if (value === undefined || value.startsWith("--")) {
      throw new Error(`missing value for --${name}`);
    }
    recordOption(values, allowed, name, value);
    index++;
  }

  const surface = values.surface ?? DEFAULTS.surface;
  const source = values.source ?? DEFAULTS.source;
  const mode = values.mode ?? DEFAULTS.mode;
  const locale = values.locale ?? env.FDAI_LOCALE ?? DEFAULTS.locale;
  const apiUrl = values.api ?? DEFAULTS.apiUrl;

  if (!isOneOf(surface, ["cli", "text", "slack", "teams"])) {
    throw new Error(`unknown --surface=${surface} (cli | text | slack | teams)`);
  }
  if (!isOneOf(source, ["sample", "api"])) {
    throw new Error(`unknown --source=${source} (sample | api)`);
  }
  if (!isOneOf(mode, ["needs-me", "all-clear"])) {
    throw new Error(`unknown --mode=${mode} (needs-me | all-clear)`);
  }
  if (!isOneOf(locale, ["en", "ko"])) {
    throw new Error(`unknown --locale=${locale} (en | ko)`);
  }
  validateApiUrl(apiUrl);

  return { surface, source, mode, locale, apiUrl };
}

function validateApiUrl(raw: string): void {
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    throw new Error(`invalid --api URL: ${raw}`);
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("--api URL must use http or https");
  }
  if (parsed.username || parsed.password) {
    throw new Error("--api URL must not contain credentials");
  }
  if (parsed.search || parsed.hash) {
    throw new Error("--api URL must not contain a query or fragment");
  }
}

function recordOption(
  values: Record<string, string>,
  allowed: ReadonlySet<string>,
  name: string,
  value: string,
): void {
  if (!allowed.has(name)) {
    throw new Error(`unknown option --${name}`);
  }
  if (Object.hasOwn(values, name)) {
    throw new Error(`duplicate option --${name}`);
  }
  if (value === "") {
    throw new Error(`missing value for --${name}`);
  }
  values[name] = value;
}

function isOneOf<const T extends string>(value: string, allowed: readonly T[]): value is T {
  return allowed.includes(value as T);
}
