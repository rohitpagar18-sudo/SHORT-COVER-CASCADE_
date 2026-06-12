import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api, type ConfigData, type PutConfigResult } from "../lib/api";

interface ConfigCtx {
  config: ConfigData | null;
  loading: boolean;
  error: string | null;
  save: (changes: Record<string, unknown>) => Promise<PutConfigResult>;
  reload: () => void;
}

const ConfigContext = createContext<ConfigCtx | null>(null);

export function ConfigProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<ConfigData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchConfig = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getConfig();
      setConfig(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load config");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  const save = useCallback(
    async (changes: Record<string, unknown>): Promise<PutConfigResult> => {
      const result = await api.putConfig(changes);
      // Re-sync remote state after a successful write
      await fetchConfig();
      return result;
    },
    [fetchConfig],
  );

  return (
    <ConfigContext.Provider value={{ config, loading, error, save, reload: fetchConfig }}>
      {children}
    </ConfigContext.Provider>
  );
}

export function useConfig(): ConfigCtx {
  const ctx = useContext(ConfigContext);
  if (!ctx) throw new Error("useConfig must be used within <ConfigProvider>");
  return ctx;
}
