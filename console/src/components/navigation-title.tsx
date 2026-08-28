import { createContext, type ComponentChildren } from "preact";
import { useContext } from "preact/hooks";
import { PANEL_GROUPS, panelForId } from "../panels";

interface NavigationTitleContextValue {
  readonly domain: string | null;
  readonly explorerOpen: boolean;
  readonly openExplorer: (() => void) | null;
}

const NavigationTitleContext = createContext<NavigationTitleContextValue>({
  domain: null,
  explorerOpen: false,
  openExplorer: null,
});
const DUPLICATE_TITLE_ROOT_PANEL_IDS = new Set(["agents", "labs"]);

interface ProviderProps {
  readonly activePanelId: string;
  readonly explorerOpen: boolean;
  readonly onOpenExplorer: () => void;
  readonly children: ComponentChildren;
}

export function navigationDomainForPanel(activePanelId: string): string | null {
  const panel = panelForId(activePanelId);
  if (panel.placement === "bottom" || DUPLICATE_TITLE_ROOT_PANEL_IDS.has(panel.id)) return null;
  const group = PANEL_GROUPS.find((candidate) => candidate.id === panel.group);
  if (group === undefined) return null;
  return group.label;
}

export function NavigationTitleProvider({
  activePanelId,
  explorerOpen,
  onOpenExplorer,
  children,
}: ProviderProps) {
  const panel = panelForId(activePanelId);
  return (
    <NavigationTitleContext.Provider
      value={{
        domain: navigationDomainForPanel(activePanelId),
        explorerOpen,
        openExplorer: panel.placement === "bottom" ? null : onOpenExplorer,
      }}
    >
      {children}
    </NavigationTitleContext.Provider>
  );
}

export function useNavigationDomain(): string | null {
  return useContext(NavigationTitleContext).domain;
}

export function useNavigationExplorer() {
  const { explorerOpen, openExplorer } = useContext(NavigationTitleContext);
  return { explorerOpen, openExplorer };
}
