"use client";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { oracleRepository } from "@/lib/oracle/mock-repository";
import {
  defaultSettings,
  dossierFixtures,
  signalFixtures,
} from "@/lib/oracle/fixtures";
import {
  readAddedDossiers,
  readSettings,
  readSignalActions,
  setStorageTenant,
} from "@/lib/oracle/storage";
import type {
  CreateDossierInput,
  Signal,
  SignalAction,
  StrategicDossier,
  UserSettings,
} from "@/lib/oracle/types";

interface OracleContextValue {
  dossiers: StrategicDossier[];
  signals: Signal[];
  settings: UserSettings;
  loading: boolean;
  createDossier: (v: CreateDossierInput) => Promise<StrategicDossier>;
  actOnSignal: (v: SignalAction) => Promise<void>;
  saveSettings: (v: UserSettings) => Promise<void>;
  reload: () => void;
}
const OracleContext = createContext<OracleContextValue | null>(null);

export function OracleProvider({ children }: { children: React.ReactNode }) {
  const [dossiers, setDossiers] = useState(dossierFixtures);
  const [signals, setSignals] = useState(signalFixtures);
  const [settings, setSettings] = useState(defaultSettings);
  const [loading, setLoading] = useState(true);
  const reload = useCallback(() => {
    setDossiers([...readAddedDossiers(), ...dossierFixtures]);
    const actions = readSignalActions();
    setSignals(
      signalFixtures.map((s) => ({
        ...s,
        status: actions.find((a) => a.signalId === s.id)?.status ?? s.status,
      })),
    );
    setSettings(readSettings());
  }, []);
  useEffect(() => {
    const clearTenantView = (event: Event) => {
      setStorageTenant(
        (event as CustomEvent<{ tenantId: string | null }>).detail?.tenantId ??
          null,
      );
      reload();
    };
    const hydrate = setTimeout(reload, 0);
    const ready = setTimeout(() => setLoading(false), 320);
    window.addEventListener("oracle:reset", reload);
    window.addEventListener("oracle:tenant-changed", clearTenantView);
    return () => {
      clearTimeout(hydrate);
      clearTimeout(ready);
      window.removeEventListener("oracle:reset", reload);
      window.removeEventListener("oracle:tenant-changed", clearTenantView);
    };
  }, [reload]);
  const value = useMemo<OracleContextValue>(
    () => ({
      dossiers,
      signals,
      settings,
      loading,
      reload,
      createDossier: async (input) => {
        const d = await oracleRepository.createDossier(input);
        setDossiers((v) => [d, ...v]);
        return d;
      },
      actOnSignal: async (action) => {
        const s = await oracleRepository.updateSignal(action);
        setSignals((v) => v.map((item) => (item.id === s.id ? s : item)));
      },
      saveSettings: async (input) => {
        const v = await oracleRepository.updateUserSettings(input);
        setSettings(v);
      },
    }),
    [dossiers, signals, settings, loading, reload],
  );
  return (
    <OracleContext.Provider value={value}>
      <div data-density={settings.density}>{children}</div>
    </OracleContext.Provider>
  );
}
export function useOracle() {
  const value = useContext(OracleContext);
  if (!value) throw new Error("useOracle requiere OracleProvider");
  return value;
}
