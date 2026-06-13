import { useEffect, useMemo, useState } from "react";
import { useConfig } from "../../../context/ConfigContext";
import { useToast } from "../../../context/ToastContext";
import { SectionShell, Toggle, NumberField, SelectField } from "../index";

type SmaTrail = {
  sma_period: number;
  activate_after_minutes: number;
  update_interval_minutes: number;
  follow_direction: string;
};

type StopLossLocal = {
  method: number;
  use_vix_multiplier: boolean;
  hard_exit_red_candle_below_vwap: boolean;
  sma_trail: SmaTrail;
};

function fromConfig(config: Record<string, unknown> | null): StopLossLocal {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const s: any = (config as any)?.stop_loss ?? {};
  const t = s.sma_trail ?? {};
  return {
    method: s.method ?? 1,
    use_vix_multiplier: s.use_vix_multiplier ?? true,
    hard_exit_red_candle_below_vwap: s.hard_exit_red_candle_below_vwap ?? true,
    sma_trail: {
      sma_period: t.sma_period ?? 19,
      activate_after_minutes: t.activate_after_minutes ?? 15,
      update_interval_minutes: t.update_interval_minutes ?? 15,
      follow_direction: t.follow_direction ?? "both",
    },
  };
}

export function StopLossSection() {
  const { config, save, reload } = useConfig();
  const toast = useToast();
  const [local, setLocal] = useState<StopLossLocal>(() => fromConfig(config));

  useEffect(() => {
    setLocal(fromConfig(config));
  }, [config]);

  const remote = useMemo(() => fromConfig(config), [config]);
  const isDirty = JSON.stringify(local) !== JSON.stringify(remote);
  const trailEnabled = local.method === 3;

  const setSma = (patch: Partial<SmaTrail>) =>
    setLocal((prev) => ({ ...prev, sma_trail: { ...prev.sma_trail, ...patch } }));

  const handleSave = async () => {
    const result = await save({ stop_loss: local } as Record<string, unknown>);
    if (result.updated) {
      toast.push("Saved — applies on the bot's next scan.", "ok");
    }
    return result;
  };

  const handleReload = () => {
    setLocal(remote);
    reload();
  };

  return (
    <SectionShell
      title="Stop Loss"
      subtitle="How the bot computes the SL price after a valid signal. Method 3 enables the SMA trail."
      onSave={handleSave}
      isDirty={isDirty}
      onReload={handleReload}
    >
      <SelectField
        label="Stop Loss Method"
        helper="Method 3 trails SL on the option's N-SMA after the activation window."
        value={String(local.method)}
        options={[
          { value: "1", label: "1 — Point Buffer" },
          { value: "2", label: "2 — Percentage" },
          { value: "3", label: "3 — Initial SL then 19-SMA Trail" },
        ]}
        onChange={(v) =>
          setLocal((prev) => ({ ...prev, method: Number(v) }))
        }
      />

      <Toggle
        label="Use VIX Multiplier"
        helper="Multiply SL buffer by VIX regime factor. OFF = base buffer only (riskier in high vol)."
        value={local.use_vix_multiplier}
        onChange={(v) =>
          setLocal((prev) => ({ ...prev, use_vix_multiplier: v }))
        }
      />

      <Toggle
        label="Hard Exit (Red Candle Below VWAP)"
        helper="ON = exit immediately on a full red candle below VWAP. Overrides SL — emergency rule."
        value={local.hard_exit_red_candle_below_vwap}
        onChange={(v) =>
          setLocal((prev) => ({ ...prev, hard_exit_red_candle_below_vwap: v }))
        }
      />

      {/* SMA Trail Panel — only active when method === 3 */}
      <div className="py-3">
        <div
          className={[
            "rounded-lg border p-4 transition-opacity",
            trailEnabled
              ? "border-slate-200 bg-slate-50"
              : "border-slate-200 bg-slate-50 opacity-60",
          ].join(" ")}
        >
          <div className="mb-1 flex items-center justify-between">
            <div className="text-xs font-semibold uppercase tracking-wide text-muted">
              SMA Trail Settings (Method 3)
            </div>
            {!trailEnabled && (
              <span className="rounded-full bg-slate-200 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted">
                Inactive
              </span>
            )}
          </div>
          {!trailEnabled && (
            <div className="mb-2 text-xs italic text-muted">
              Active only when Method 3 is selected.
            </div>
          )}
          <div className="divide-y divide-slate-200">
            <NumberField
              label="SMA Period"
              helper="Period for the simple moving average on option close (default 19)"
              value={local.sma_trail.sma_period}
              min={1}
              disabled={!trailEnabled}
              onChange={(v) => setSma({ sma_period: v })}
              suffix="candles"
            />
            <NumberField
              label="Activate After"
              helper="First N minutes after entry uses the Method-1 SL, then convert to SMA trail"
              value={local.sma_trail.activate_after_minutes}
              min={1}
              disabled={!trailEnabled}
              onChange={(v) => setSma({ activate_after_minutes: v })}
              suffix="min"
            />
            <NumberField
              label="Update Interval"
              helper="Re-evaluate the trailing SL every N minutes"
              value={local.sma_trail.update_interval_minutes}
              min={1}
              disabled={!trailEnabled}
              onChange={(v) => setSma({ update_interval_minutes: v })}
              suffix="min"
            />
            <SelectField
              label="Follow Direction"
              helper="'Both' lets SL move up AND down with the SMA. 'Ratchet' is up-only."
              value={local.sma_trail.follow_direction}
              disabled={!trailEnabled}
              options={[
                { value: "both",    label: "Both (Up & Down)" },
                { value: "ratchet", label: "Ratchet (Up only)" },
              ]}
              onChange={(v) => setSma({ follow_direction: v })}
            />
          </div>
        </div>
      </div>
    </SectionShell>
  );
}
