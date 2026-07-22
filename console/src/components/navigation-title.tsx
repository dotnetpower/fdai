import { createContext, type ComponentChildren } from "preact";
import { useContext } from "preact/hooks";
import { PANEL_GROUPS, panelForId } from "../panels";

const NavigationDomainContext = createContext<string | null>(null);
const DUPLICATE_TITLE_ROOT_PANEL_IDS = new Set(["agents", "labs"]);

interface ProviderProps {
  readonly activePanelId: string;
  readonly children: ComponentChildren;
}

export function navigationDomainForPanel(activePanelId: string): string | null {
  const panel = panelForId(activePanelId);
  if (panel.placement === "bottom" || DUPLICATE_TITLE_ROOT_PANEL_IDS.has(panel.id)) return null;
  const group = PANEL_GROUPS.find((candidate) => candidate.id === panel.group);
  if (group === undefined) return null;
  return group.label;
}

export function NavigationTitleProvider({ activePanelId, children }: ProviderProps) {
  return (
    <NavigationDomainContext.Provider value={navigationDomainForPanel(activePanelId)}>
      {children}
    </NavigationDomainContext.Provider>
  );
}

export function useNavigationDomain(): string | null {
  return useContext(NavigationDomainContext);
}
