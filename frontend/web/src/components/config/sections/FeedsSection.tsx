import { useEffect, useState } from "react";
import { useConfig } from "../../../context/ConfigContext";
import { SectionShell, RadioCards, Toggle, NumberField } from "../index";

type FeedsLocal = {
  active_feed: string;
  healthcheck_timeout_seconds: number;
  upstox: { enabled: boolean; token_validity_days: number };
  kite: { enabled: boolean; token_validity_days: number };
};

function fromConfig(config: Record<string, unknown> | null): FeedsLocal {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const f: any = (config as any)?.feeds ?? {};
  return {
    active_feed: f.active_feed ?? "kite",
    healthcheck_timeout_seconds: f.healthcheck_timeout_seconds ?? 10,
    upstox: {
      enabled: f.upstox?.enabled ?? true,
      token_validity_days: f.upstox?.token_validity_days ?? 365,
    },
    kite: {
      enabled: f.kite?.enabled ?? true,
      token_validity_days: f.kite?.token_validity_days ?? 1,
    },
  };
}

export function FeedsSection() {
  const { config, save, reload } = useConfig();
  const [local, setLocal] = useState<FeedsLocal>(() => fromConfig(config));

  useEffect(() => {
    setLocal(fromConfig(config));
  }, [config]);

  const remote = fromConfig(config);
  const isDirty = JSON.stringify(local) !== JSON.stringify(remote);

  const set = (patch: Partial<FeedsLocal>) =>
    setLocal((prev) => ({ ...prev, ...patch }));
  const setUpstox = (patch: Partial<FeedsLocal["upstox"]>) =>
    setLocal((prev) => ({ ...prev, upstox: { ...prev.upstox, ...patch } }));
  const setKite = (patch: Partial<FeedsLocal["kite"]>) =>
    setLocal((prev) => ({ ...prev, kite: { ...prev.kite, ...patch } }));

  const handleSave = () =>
    save({ feeds: local } as Record<string, unknown>);

  const handleReload = () => {
    setLocal(remote);
    reload();
  };

  return (
    <SectionShell
      title="Broker Feed"
      subtitle="Which broker the bot uses for live data. Switching the active feed requires a bot restart."
      onSave={handleSave}
      isDirty={isDirty}
      onReload={handleReload}
    >
      <RadioCards
        label="Active Feed"
        helper="Only one feed is active at a time. The other makes zero API calls."
        value={local.active_feed}
        options={[
          {
            value: "kite",
            label: "Kite (Zerodha)",
            description: "Daily token refresh required (SEBI rule)",
          },
          {
            value: "upstox",
            label: "Upstox",
            description: "365-day token via Analytics tab",
          },
        ]}
        onChange={(v) => set({ active_feed: v })}
      />

      <NumberField
        label="Healthcheck Timeout"
        helper="Seconds to wait before declaring the feed unreachable"
        value={local.healthcheck_timeout_seconds}
        min={1}
        max={60}
        onChange={(v) => set({ healthcheck_timeout_seconds: v })}
        suffix="sec"
      />

      <div className="py-3">
        <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">
          Kite
        </div>
        <Toggle
          label="Kite Enabled"
          helper="Permit switching to Kite. OFF = totally disabled, no API calls."
          value={local.kite.enabled}
          onChange={(v) => setKite({ enabled: v })}
        />
        <NumberField
          label="Token Validity"
          helper="1 = daily refresh required (SEBI individual rule)"
          value={local.kite.token_validity_days}
          min={1}
          onChange={(v) => setKite({ token_validity_days: v })}
          suffix="day(s)"
        />
      </div>

      <div className="py-3">
        <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">
          Upstox
        </div>
        <Toggle
          label="Upstox Enabled"
          helper="Permit switching to Upstox. OFF = totally disabled, no API calls."
          value={local.upstox.enabled}
          onChange={(v) => setUpstox({ enabled: v })}
        />
        <NumberField
          label="Token Validity"
          helper="365 = use the long-lived Analytics tab token, no daily refresh"
          value={local.upstox.token_validity_days}
          min={1}
          max={365}
          onChange={(v) => setUpstox({ token_validity_days: v })}
          suffix="day(s)"
        />
      </div>
    </SectionShell>
  );
}
