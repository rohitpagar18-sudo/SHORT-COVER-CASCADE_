import { useEffect, useMemo, useState } from "react";
import { useConfig } from "../../../context/ConfigContext";
import { useToast } from "../../../context/ToastContext";
import { SectionShell, NumberField, Toggle } from "../index";

type AlertStrikes = {
  itm3: boolean;
  itm2: boolean;
  itm1: boolean;
  atm: boolean;
  otm1: boolean;
  otm2: boolean;
  otm3: boolean;
};

type OrderStrikes = {
  itm: boolean;
  atm: boolean;
  otm: boolean;
};

type StrikeLocal = {
  max_deviation_from_atm: number;
  late_entry_threshold_percent: number;
  alert_strikes: AlertStrikes;
  order_strikes: OrderStrikes;
};

const ALERT_ORDER: (keyof AlertStrikes)[] = [
  "itm3", "itm2", "itm1", "atm", "otm1", "otm2", "otm3",
];

const ALERT_LABELS: Record<keyof AlertStrikes, string> = {
  itm3: "ITM3",
  itm2: "ITM2",
  itm1: "ITM1",
  atm: "ATM",
  otm1: "OTM1",
  otm2: "OTM2",
  otm3: "OTM3",
};

function fromConfig(config: Record<string, unknown> | null): StrikeLocal {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const s: any = (config as any)?.strike ?? {};
  const a = s.alert_strikes ?? {};
  const o = s.order_strikes ?? {};
  return {
    max_deviation_from_atm: s.max_deviation_from_atm ?? 1,
    late_entry_threshold_percent: s.late_entry_threshold_percent ?? 30,
    alert_strikes: {
      itm3: a.itm3 ?? false,
      itm2: a.itm2 ?? false,
      itm1: a.itm1 ?? false,
      atm:  a.atm  ?? false,
      otm1: a.otm1 ?? false,
      otm2: a.otm2 ?? false,
      otm3: a.otm3 ?? false,
    },
    order_strikes: {
      itm: o.itm ?? false,
      atm: o.atm ?? false,
      otm: o.otm ?? false,
    },
  };
}

export function StrikeScanningSection() {
  const { config, save, reload } = useConfig();
  const toast = useToast();
  const [local, setLocal] = useState<StrikeLocal>(() => fromConfig(config));

  useEffect(() => {
    setLocal(fromConfig(config));
  }, [config]);

  const remote = useMemo(() => fromConfig(config), [config]);
  const isDirty = JSON.stringify(local) !== JSON.stringify(remote);
  const anyAlertOn = ALERT_ORDER.some((k) => local.alert_strikes[k]);

  const setAlert = (k: keyof AlertStrikes, v: boolean) =>
    setLocal((prev) => ({
      ...prev,
      alert_strikes: { ...prev.alert_strikes, [k]: v },
    }));

  const setOrder = (k: keyof OrderStrikes, v: boolean) =>
    setLocal((prev) => ({
      ...prev,
      order_strikes: { ...prev.order_strikes, [k]: v },
    }));

  const handleSave = async () => {
    const result = await save({ strike: local } as Record<string, unknown>);
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
      title="Strike & Scanning"
      subtitle="Which option strikes the bot scans on every 5-min candle close, and which depths can fire alerts or auto-orders."
      onSave={handleSave}
      isDirty={isDirty}
      onReload={handleReload}
      saveDisabled={!anyAlertOn}
      saveDisabledHint="At least one alert strike must be enabled"
    >
      {/* Group 1 — Strike Scanning Range */}
      <div className="py-3">
        <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">
          Strike Scanning Range
        </div>
        <NumberField
          label="Max Deviation from ATM"
          helper="Hard cap — bot never scans beyond ± this many strikes from ATM"
          value={local.max_deviation_from_atm}
          min={0}
          onChange={(v) =>
            setLocal((prev) => ({ ...prev, max_deviation_from_atm: v }))
          }
          suffix="strike(s)"
        />
        <NumberField
          label="Late Entry Threshold (%)"
          helper="If the option is already this % above its VWAP, skip — chasing"
          value={local.late_entry_threshold_percent}
          min={0}
          step={0.5}
          onChange={(v) =>
            setLocal((prev) => ({ ...prev, late_entry_threshold_percent: v }))
          }
          suffix="%"
        />
      </div>

      {/* Group 2 — Alert Strikes */}
      <div className="py-3">
        <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">
          Alert Strikes (Scan & Alert)
        </div>
        <div className="text-xs text-muted">
          Each depth is independent — non-contiguous combos allowed
          (e.g. ITM1 on, ITM2 off, ITM3 on).
        </div>
        <div className="mt-3 grid grid-cols-7 gap-2">
          {ALERT_ORDER.map((k) => {
            const on = local.alert_strikes[k];
            return (
              <button
                key={k}
                type="button"
                role="switch"
                aria-checked={on}
                onClick={() => setAlert(k, !on)}
                className={[
                  "flex flex-col items-center gap-1 rounded-lg border-2 px-2 py-2 text-xs font-medium transition-colors",
                  "focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-1",
                  on
                    ? "border-emerald-500 bg-emerald-50 text-emerald-700"
                    : "border-slate-200 bg-white text-muted hover:border-slate-300",
                ].join(" ")}
              >
                <span className="font-semibold tracking-wide">
                  {ALERT_LABELS[k]}
                </span>
                <span
                  className={[
                    "rounded px-1.5 py-0.5 text-[10px] font-bold",
                    on ? "bg-emerald-500 text-white" : "bg-slate-200 text-slate-500",
                  ].join(" ")}
                >
                  {on ? "ON" : "OFF"}
                </span>
              </button>
            );
          })}
        </div>
        {!anyAlertOn && (
          <div className="mt-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
            At least one alert strike must be enabled.
          </div>
        )}
      </div>

      {/* Group 3 — Auto Order Strikes */}
      <div className="py-3">
        <div className="mb-1 flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted">
            Auto Order Strikes
          </span>
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted">
            Phase 8
          </span>
        </div>
        <div className="text-xs text-muted">
          Safer to start with ATM only. Add others after you trust the bot.
        </div>
        <Toggle
          label="ITM Order"
          helper="Auto-place orders on ITM strikes when alerts fire"
          value={local.order_strikes.itm}
          onChange={(v) => setOrder("itm", v)}
        />
        <Toggle
          label="ATM Order"
          helper="ATM is the safest default to auto-order"
          value={local.order_strikes.atm}
          onChange={(v) => setOrder("atm", v)}
        />
        <Toggle
          label="OTM Order"
          helper="Auto-place orders on OTM strikes when alerts fire"
          value={local.order_strikes.otm}
          onChange={(v) => setOrder("otm", v)}
        />
      </div>
    </SectionShell>
  );
}
