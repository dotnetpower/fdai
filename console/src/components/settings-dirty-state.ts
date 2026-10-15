import { createContext } from "preact";
import { useContext, useEffect } from "preact/hooks";

export type SettingsDirtyRegistration = (source: string, dirty: boolean) => void;

export const SettingsDirtyContext = createContext<SettingsDirtyRegistration>(() => undefined);

export function useSettingsDirtyState(source: string, dirty: boolean): void {
  const register = useContext(SettingsDirtyContext);
  useEffect(() => {
    register(source, dirty);
    return () => register(source, false);
  }, [dirty, register, source]);
}
