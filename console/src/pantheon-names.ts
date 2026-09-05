export const PANTHEON_NAMES = [
  "Odin",
  "Heimdall",
  "Huginn",
  "Forseti",
  "Var",
  "Thor",
  "Vidar",
  "Saga",
  "Bragi",
  "Njord",
  "Freyr",
  "Loki",
  "Mimir",
  "Norns",
  "Muninn",
] as const;

export const PANTHEON_NAME_SET: ReadonlySet<string> = new Set(PANTHEON_NAMES);
