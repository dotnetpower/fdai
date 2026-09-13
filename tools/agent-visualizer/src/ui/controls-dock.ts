/** Reserve only the stable camera row, even when locale or viewport changes its wrapping. */
export function observeControlsDock(root: HTMLElement): () => void {
  const toolbar = root.querySelector<HTMLElement>(".view-toolbar");
  if (!toolbar) throw new Error("The controls dock camera row is missing.");
  const update = () => {
    const height = toolbar.getBoundingClientRect().height;
    if (height > 0) root.style.setProperty("--dock-toolbar-height", `${Math.ceil(height)}px`);
  };
  const observer = new ResizeObserver(update);
  observer.observe(toolbar);
  update();
  return () => observer.disconnect();
}
