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

type ConditionsLocal = {
  c3_rsi_min: number;
  c3_rsi_max: number;
  c0_spot_trend_filter_enabled: boolean;
  c1_max_distance_pct: number;
  c1_extended_zone_enabled: boolean;
  c1_extended_zone_max_pct: number;
  c5_adx: C5Adx;
};

function CardHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="border-b border-slate-200 px-4 py-3">
      <div className="text-sm font-semibold text-ink">{title}</div>
      {subtitle && <div className="mt-0.5 text-xs text-muted">{subtitle}</div>}
    </div>
  );
}

function fromConfig(config: Record<string, unknown> | null): ConditionsLocal {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c: any = (config as any)?.conditions ?? {};
  const adx = c.c5_adx ?? {};
  return {
    c3_rsi_min: c.c3_rsi_min ?? 50,
    c3_rsi_max: c.c3_rsi_max ?? 80,
    c0_spot_trend_filter_enabled: c.c0_spot_trend_filter_enabled ?? false,
    c1_max_distance_pct: c.c1_max_distance_pct ?? 30,
    c1_extended_zone_enabled: c.c1_extended_zone_enabled ?? true,
    c1_extended_zone_max_pct: c.c1_extended_zone_max_pct ?? 50,
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

  useEffect(() => {
    setLocal(fromConfig(config));
  }, [config]);

  const remote = useMemo(() => fromConfig(config), [config]);
  const isDirty = JSON.stringify(local) !== JSON.stringify(remote);

  const rsiInvalid = local.c3_rsi_min >= local.c3_rsi_max;
  const gatingWithoutEnabled = local.c5_adx.gating && !local.c5_adx.enabled;

  const setAdx = (patch: Partial<C5Adx>) =>
    setLocal((prev) => ({ ...prev, c5_adx: { ...prev.c5_adx, ...patch } }));

  const handleSave = async () => {
    const result = await save({ conditions: local } as Record<string, unknown>);
    if (result.updated) {
      toast.push("Saved — applies on the bot's next scan.", "ok");
    }
    return result;
  };

  const handleReload = () => {
    setLocal(remote);
    reload();
  };

  const saveDisabled = rsiInvalid || gatingWithoutEnabled;
  const saveDisabledHint = rsiInvalid
    ? "RSI Min must be less than RSI Max"
    : gatingWithoutEnabled
    ? "C5 gating requires Enabled to be ON first"
    : undefined;

  return (
    <SectionShell
      title="Conditions (C0–C5)"
      subtitle="Thresholds for each scan condition. Changes apply on the bot's next 5-min scan."
      onSave={handleSave}
      isDirty={isDirty}
      onReload={handleReload}
      saveDisabled={saveDisabled}
      saveDisabledHint={saveDisabledHint}
    >
      {/* C3 RSI Filter */}
      <div className="py-3">
        <div className="rounded-lg border border-slate-200 bg-white">
          <CardHeader
            title="C3 — RSI Filter"
            subtitle="RSI(14) must fall within this band. Uses Wilder's smoothing (RMA), not simple or exponential MA."
          />
          <div className="divide-y divide-slate-100 px-4">
            <NumberField
              label="RSI Min"
              helper="RSI must be ABOVE this (momentum present). Default 50."
              value={local.c3_rsi_min}
              min={0}
              max={100}
              onChange={(v) => setLocal((prev) => ({ ...prev, c3_rsi_min: v }))}
            />
            <NumberField
              label="RSI Max"
              helper="RSI must be BELOW this (overbought guard). Default 80."
              value={local.c3_rsi_max}
              min={0}
              max={100}
              onChange={(v) => setLocal((prev) => ({ ...prev, c3_rsi_max: v }))}
            />
            {rsiInvalid && (
              <div className="py-2 text-xs font-medium text-rose-600">
                RSI Min must be less than RSI Max.
              </div>
            )}
          </div>
        </div>
      </div>

      {/* C0 Spot Trend Filter */}
      <div className="py-3">
        <div className="rounded-lg border border-slate-200 bg-white">
          <CardHeader title="C0 — Spot Trend Filter" />
          <div className="divide-y divide-slate-100 px-4">
            <Toggle
              label="Spot Trend Filter Enabled"
              helper="OFF (recommended) = scan both CE & PE on every candle, let C1–C4 decide. ON = CE only when spot above VWAP, PE only when below."
              value={local.c0_spot_trend_filter_enabled}
              onChange={(v) =>
                setLocal((prev) => ({ ...prev, c0_spot_trend_filter_enabled: v }))
              }
            />
          </div>
        </div>
      </div>

      {/* C1 Late Entry Filter */}
      <div className="py-3">
        <div className="rounded-lg border border-slate-200 bg-white">
          <CardHeader
            title="C1 — Late Entry Filter"
            subtitle="Rejects options that have already run too far above their own VWAP."
          />
          <div className="divide-y divide-slate-100 px-4">
            <NumberField
              label="Max Distance (%)"
              helper="Reject alerts where the option is more than this % above its own VWAP."
              value={local.c1_max_distance_pct}
              min={0}
              step={0.5}
              suffix="%"
              onChange={(v) => setLocal((prev) => ({ ...prev, c1_max_distance_pct: v }))}
            />
            <Toggle
              label="Extended Zone Enabled"
              helper="Log options 30–50% above VWAP as 'would_alert_extended' (data collection for future threshold tuning)."
              value={local.c1_extended_zone_enabled}
              onChange={(v) =>
                setLocal((prev) => ({ ...prev, c1_extended_zone_enabled: v }))
              }
            />
            <NumberField
              label="Extended Zone Max (%)"
              helper="Upper bound for extended-zone logging. Must be ≥ Max Distance."
              value={local.c1_extended_zone_max_pct}
              min={0}
              step={0.5}
              suffix="%"
              onChange={(v) =>
                setLocal((prev) => ({ ...prev, c1_extended_zone_max_pct: v }))
              }
            />
          </div>
        </div>
      </div>

      {/* C5 ADX Shadow Mode */}
      <div className="py-3">
        <div className="rounded-lg border border-slate-200 bg-white">
          <CardHeader
            title="C5 — ADX Trend Filter (Shadow Mode)"
            subtitle="Measures trend strength via ADX(14). While gating is OFF: computed, logged, shown on alerts — but never blocks a signal."
          />
          <div className="divide-y divide-slate-100 px-4">
            <Toggle
              label="Enabled"
              helper="ON = compute, log, and display C5 on every scan. OFF = C5 absent entirely (not computed, not logged, not shown)."
              value={local.c5_adx.enabled}
              onChange={(v) => {
                // Turning Enabled OFF forces Gating OFF too.
                setAdx({ enabled: v, gating: v ? local.c5_adx.gating : false });
              }}
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
                  <span className="font-semibold">Gating ON</span> — alerts will require
                  C1 through C5 to all pass. This narrows which setups fire. Review
                  Phase 7 data before enabling in a live session.
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
              helper="adx > adx_prev — ADX must be gaining strength, not just above the threshold (ignition filter)."
              value={local.c5_adx.require_rising}
              disabled={!local.c5_adx.enabled}
              onChange={(v) => setAdx({ require_rising: v })}
            />
            <Toggle
              label="Use DI Alignment"
              helper="OFF (recommended) = trend strength only. ON = also require +DI / −DI alignment. Direction is already covered by C0 + C1, so alignment adds noise."
              value={local.c5_adx.use_di_alignment}
              disabled={!local.c5_adx.enabled}
              onChange={(v) => setAdx({ use_di_alignment: v })}
            />
            <NumberField
              label="Lookback Candles"
              helper="Rolling multi-day window for ADX history (~150 = 2 sessions). NOT session-anchored — ADX needs stable history at market open."
              value={local.c5_adx.lookback_candles}
              min={1}
              disabled={!local.c5_adx.enabled}
              onChange={(v) => setAdx({ lookback_candles: v })}
            />
          </div>
        </div>
      </div>
    </SectionShell>
  );
}
