import { createContext, type ComponentChildren } from "preact";
import { useContext } from "preact/hooks";
import { PANEL_GROUPS, panelForId } from "../panels";

const NavigationDomainContext = createContext<string | null>(null);

interface ProviderProps {
  readonly activePanelId: string;
  readonly children: ComponentChildren;
}

export function navigationDomainForPanel(activePanelId: string): string | null {
  const panel = panelForId(activePanelId);
  if (panel.placement === "bottom") return null;
  const group = PANEL_GROUPS.find((candidate) => candidate.id === panel.group);
  if (group === undefined || group.label === panel.label) return null;
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