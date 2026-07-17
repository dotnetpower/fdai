export interface DeckSlashCommand {
  readonly name: string;
  readonly aliases: readonly string[];
  readonly summary: string;
}

export const DECK_SLASH_COMMANDS: readonly DeckSlashCommand[] = [
  { name: "new", aliases: ["n"], summary: "Start a new conversation" },
  { name: "clear", aliases: ["c"], summary: "Clear this conversation's cached transcript" },
  { name: "close", aliases: ["q"], summary: "Close the command deck" },
  { name: "help", aliases: ["?", "h"], summary: "List the available slash commands" },
];

export function matchSlashCommand(
  input: string,
): { readonly canonical: string; readonly token: string } | null {
  const trimmed = input.trim();
  if (!trimmed.startsWith("/") || trimmed.length < 2) return null;
  const token = trimmed.slice(1).split(/\s+/, 1)[0]?.toLowerCase() ?? "";
  for (const command of DECK_SLASH_COMMANDS) {
    if (command.name === token || command.aliases.includes(token)) {
      return { canonical: command.name, token };
    }
  }
  return { canonical: "", token };
}

export function slashHelpText(): string {
  const lines = DECK_SLASH_COMMANDS.map((command) => {
    const alias = command.aliases.length > 0
      ? ` (/${command.aliases.join(", /")})`
      : "";
    return `/${command.name}${alias} - ${command.summary}`;
  });
  return ["Available commands:", ...lines].join("\n");
}
