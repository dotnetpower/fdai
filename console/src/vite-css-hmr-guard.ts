import type { Plugin } from "vite";

export async function stabilizeCssHotUpdate(
  file: string,
  read: () => string | Promise<string>,
): Promise<void> {
  if (!file.endsWith(".css")) return;
  await read();
}

export function cssHotUpdateGuard(): Plugin {
  return {
    name: "fdai:transient-css-hmr-guard",
    apply: "serve",
    handleHotUpdate: {
      order: "pre",
      async handler({ file, read }) {
        await stabilizeCssHotUpdate(file, read);
      },
    },
  };
}
