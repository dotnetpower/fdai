import type { CockpitRenderer } from "./cockpit-renderer.js";
import type { CockpitState } from "./cockpit-state.js";
import { safeDisplayText } from "./display-text.js";

const ESC = "\x1b";
export const MAX_CLI_INPUT_CODE_POINTS = 4096;
export const MAX_CLI_LOCAL_HISTORY = 100;

export function createInputController(
  state: CockpitState,
  renderer: CockpitRenderer,
  submit: () => void,
  finish: () => void,
): (data: string) => void {
  return (data: string): void => {
    if (data === "\x03") {
      finish();
      return;
    }
    if (state.busy) return;
    if (data === "\r" || data === "\n") return submit();
    if (data === "\x7f" || data === "\b") {
      if (state.cursor > 0) {
        state.input.splice(state.cursor - 1, 1);
        state.cursor--;
        renderer.renderInput();
      }
      return;
    }
    if (data === `${ESC}[D`) {
      if (state.cursor > 0) state.cursor--;
      renderer.renderInput();
      return;
    }
    if (data === `${ESC}[C`) {
      if (state.cursor < state.input.length) state.cursor++;
      renderer.renderInput();
      return;
    }
    if (data === `${ESC}[A`) {
      if (state.history.length === 0) return;
      state.historyIndex =
        state.historyIndex === null
          ? state.history.length - 1
          : Math.max(0, state.historyIndex - 1);
      state.input = [...state.history[state.historyIndex]!];
      state.cursor = state.input.length;
      renderer.renderInput();
      return;
    }
    if (data === `${ESC}[B`) {
      if (state.historyIndex === null) return;
      state.historyIndex += 1;
      if (state.historyIndex >= state.history.length) {
        state.historyIndex = null;
        state.input = [];
      } else state.input = [...state.history[state.historyIndex]!];
      state.cursor = state.input.length;
      renderer.renderInput();
      return;
    }
    if (data === "\x01" || data === `${ESC}[H`) {
      state.cursor = 0;
      renderer.renderInput();
      return;
    }
    if (data === "\x05" || data === `${ESC}[F`) {
      state.cursor = state.input.length;
      renderer.renderInput();
      return;
    }
    if (data === "\x17") {
      let index = state.cursor;
      while (index > 0 && state.input[index - 1] === " ") index--;
      while (index > 0 && state.input[index - 1] !== " ") index--;
      state.input.splice(index, state.cursor - index);
      state.cursor = index;
      renderer.renderInput();
      return;
    }
    if (data === "\x15") {
      state.input = [];
      state.cursor = 0;
      renderer.renderInput();
      return;
    }
    if (data === "\x04") {
      if (state.input.length === 0) finish();
      return;
    }
    if (data.startsWith(ESC)) return;
    const newline = data.search(/[\r\n]/);
    const printable = safeDisplayText(
      newline >= 0 ? data.slice(0, newline) : data,
      MAX_CLI_INPUT_CODE_POINTS,
    );
    if (printable) {
      const available = Math.max(0, MAX_CLI_INPUT_CODE_POINTS - state.input.length);
      const inserted = [...printable].slice(0, available);
      state.input.splice(state.cursor, 0, ...inserted);
      state.cursor += inserted.length;
    }
    if (newline >= 0) return submit();
    renderer.renderInput();
  };
}
