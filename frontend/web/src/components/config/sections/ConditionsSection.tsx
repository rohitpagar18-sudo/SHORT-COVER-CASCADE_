import { useEffect, useMemo, useState } from "react";
import { useConfig } from "../../../context/ConfigContext";
import { useToast } from "../../../context/ToastContext";
import { SectionShell, Toggle, NumberField } from "../index";

type C5Adx = {
  enabled: boolean;
  gating: boolean;
  period: number;
  adx_min: number;
  require_rising: boolean;
  use_di_alignment: boolean;
  lookback_candles: number;
};

type ConditionsLocal = { c5_adx: C5Adx };

function fromConfig(config: Record<string, unknown> | null): ConditionsLocal {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const adx = ((config as any)?.conditions?.c5_adx) ?? {};
  return {
    c5_adx: {
      enabled: adx.enabled ?? true,
      gating: adx.gating ?? false,
      period: adx.period ?? 14,
      adx_min: adx.adx_min ?? 20,
      require_rising: adx.require_rising ?? true,
      use_di_alignment: adx.use_di_alignment ?? false,
      lookback_candles: adx.lookback_candles ?? 150,
    },
  };
}

export function ConditionsSection() {
  const { config, save, reload } = useConfig();
  const toast = useToast();
  const [local, setLocal] = useState<ConditionsLocal>(() => fromConfig(config));

  useEffect(() => { setLocal(fromConfig(config)); }, [config]);

  const remote = useMemo(() => fromConfig(config), [config]);
  const isDirty = JSON.stringify(local) !== JSON.stringify(remote);
  const gatingWithoutEnabled = local.c5_adx.gating && !local.c5_adx.enabled;

  const setAdx = (patch: Partial<C5Adx>) =>
    setLocal((prev) => ({ ...prev, c5_adx: { ...prev.c5_adx, ...patch } }));

  const handleSave = async () => {
    const result = await save({ conditions: { c5_adx: local.c5_adx } } as Record<string, unknown>);
    if (result.updated) toast.push("Saved — applies on the bot's next scan.", "ok");
    return result;
  };

  const handleReload = () => { setLocal(remote); reload(); };

  return (
    <SectionShell
      title="C5 — ADX Trend Filter (Shadow Mode)"
      subtitle="Measures trend strength via ADX(14). While gating is OFF: computed, logged, shown on alerts — but never blocks a signal."
      onSave={handleSave}
      isDirty={isDirty}
      onReload={handleReload}
      saveDisabled={gatingWithoutEnabled}
      saveDisabledHint={gatingWithoutEnabled ? "C5 gating requires Enabled to be ON first" : undefined}
    >
      <Toggle
        label="Enabled"
        helper="ON = compute, log, and display C5 on every scan. OFF = C5 absent entirely."
        value={local.c5_adx.enabled}
        onChange={(v) => setAdx({ enabled: v, gating: v ? local.c5_adx.gating : false })}
      />
      <div>
        <Toggle
          label="Gating"
          helper={
            !local.c5_adx.enabled
              ? "Enable C5 first to configure gating."
              : "ON = C5 joins the trigger set (C1–C5 all must pass). OFF = shadow / data-collection only."
          }
          value={local.c5_adx.gating}
          disabled={!local.c5_adx.enabled}
          onChange={(v) => setAdx({ gating: v })}
        />
        {local.c5_adx.gating && local.c5_adx.enabled && (
          <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            <span className="font-semibold">Gating ON</span> — alerts will require C1 through C5 to all pass.
            This narrows which setups fire. Review Phase 7 data before enabling in a live session.
          </div>
        )}
      </div>
      <NumberField
        label="ADX Period"
        helper="Candles for ADX / DI calculation. Default 14, matches the RSI period."
        value={local.c5_adx.period}
        min={1}
        disabled={!local.c5_adx.enabled}
        onChange={(v) => setAdx({ period: v })}
      />
      <NumberField
        label="ADX Min"
        helper="ADX must be ≥ this value. 15 = earliest/noisiest, 20 = balanced (default), 25 = established trend."
        value={local.c5_adx.adx_min}
        min={1}
        step={0.5}
        disabled={!local.c5_adx.enabled}
        onChange={(v) => setAdx({ adx_min: v })}
      />
      <Toggle
        label="Require Rising"
        helper="adx > adx_prev — ADX must be gaining strength, not just above the threshold."
        value={local.c5_adx.require_rising}
        disabled={!local.c5_adx.enabled}
        onChange={(v) => setAdx({ require_rising: v })}
      />
      <Toggle
        label="Use DI Alignment"
        helper="OFF (recommended) = trend strength only. ON = also require +DI / −DI alignment."
        value={local.c5_adx.use_di_alignment}
        disabled={!local.c5_adx.enabled}
        onChange={(v) => setAdx({ use_di_alignment: v })}
      />
      <NumberField
        label="Lookback Candles"
        helper="Rolling multi-day window for ADX history (~150 = 2 sessions). NOT session-anchored."
        value={local.c5_adx.lookback_candles}
        min={1}
        disabled={!local.c5_adx.enabled}
        onChange={(v) => setAdx({ lookback_candles: v })}
      />
    </SectionShell>
  );
}
