import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

// User-facing UI preferences. These are PURELY localStorage state — they
// never touch config.yaml. The bot does not read these. They control how
// the dashboard polls / formats / defaults across pages.

export type DateRangePreset = "This Week" | "This Month" | "This Quarter";
export type PollInterval = 10 | 15 | 30 | 60;
export type CurrencyDisplay = "₹" | "INR";

export type UiSettings = {
  defaultDateRange: DateRangePreset;
  pollIntervalSeconds: PollInterval;
  currencyDisplay: CurrencyDisplay;
  compactNumbers: boolean;
};

export const DEFAULT_SETTINGS: UiSettings = {
  defaultDateRange: "This Month",
  pollIntervalSeconds: 15,
  currencyDisplay: "₹",
  compactNumbers: false,
};

const KEY = "scc.uiSettings.v1";

function readInitial(): UiSettings {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULT_SETTINGS;
    const parsed = JSON.parse(raw) as Partial<UiSettings>;
    return { ...DEFAULT_SETTINGS, ...parsed };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

type Ctx = {
  settings: UiSettings;
  setSettings: (s: UiSettings) => void;
  update: <K extends keyof UiSettings>(key: K, value: UiSettings[K]) => void;
  reset: () => void;
};

const SettingsCtx = createContext<Ctx | null>(null);

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettingsState] = useState<UiSettings>(readInitial);

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(settings));
    } catch {
      // ignore — private window, quota etc.
    }
  }, [settings]);

  const setSettings = useCallback((s: UiSettings) => {
    setSettingsState(s);
  }, []);

  const update = useCallback(
    <K extends keyof UiSettings>(key: K, value: UiSettings[K]) => {
      setSettingsState((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const reset = useCallback(() => setSettingsState(DEFAULT_SETTINGS), []);

  const value = useMemo(
    () => ({ settings, setSettings, update, reset }),
    [settings, setSettings, update, reset],
  );

  return <SettingsCtx.Provider value={value}>{children}</SettingsCtx.Provider>;
}

export function useSettings(): Ctx {
  const v = useContext(SettingsCtx);
  if (!v) throw new Error("useSettings must be used inside <SettingsProvider>");
  return v;
}

export function usePollIntervalMs(): number {
  const { settings } = useSettings();
  return settings.pollIntervalSeconds * 1000;
}
