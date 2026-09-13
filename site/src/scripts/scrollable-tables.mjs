/** Give only horizontally overflowing documentation tables a keyboard stop. */
export function enhanceScrollableTables(root = document) {
  const tables = [...root.querySelectorAll(".sl-markdown-content table:not([tabindex])")];
  if (tables.length === 0) return;

  const update = () => {
    for (const table of tables) {
      const scrollable = table.scrollWidth > table.clientWidth + 1;
      table.toggleAttribute("data-fdai-scrollable", scrollable);
      if (scrollable) table.setAttribute("tabindex", "0");
      else table.removeAttribute("tabindex");
    }
  };
  update();
  const observer = new ResizeObserver(update);
  tables.forEach(table => observer.observe(table));
}
