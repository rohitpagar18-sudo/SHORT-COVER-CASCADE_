import { useEffect, useMemo, useState } from "react";
import { useConfig } from "../../../context/ConfigContext";
import { useToast } from "../../../context/ToastContext";
import { SectionShell, Toggle, SelectField } from "../index";

type OrdersLocal = {
  order_type: string;
  cancel_if_price_touches_tp1: boolean;
  fallback_to_market_if_limit_disabled: boolean;
};

function fromConfig(config: Record<string, unknown> | null): OrdersLocal {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const o: any = (config as any)?.orders ?? {};
  return {
    order_type:                           o.order_type                           ?? "limit",
    cancel_if_price_touches_tp1:          o.cancel_if_price_touches_tp1          ?? true,
    fallback_to_market_if_limit_disabled: o.fallback_to_market_if_limit_disabled ?? true,
  };
}

const ORDER_TYPE_OPTIONS = [
  { value: "limit",  label: "Limit" },
  { value: "market", label: "Market" },
];

export function OrdersSection() {
  const { config, save, reload } = useConfig();
  const toast = useToast();
  const [local, setLocal] = useState<OrdersLocal>(() => fromConfig(config));

  useEffect(() => {
    setLocal(fromConfig(config));
  }, [config]);

  const remote = useMemo(() => fromConfig(config), [config]);
  const isDirty = JSON.stringify(local) !== JSON.stringify(remote);

  const set = (patch: Partial<OrdersLocal>) =>
    setLocal((prev) => ({ ...prev, ...patch }));

  const handleSave = async () => {
    const result = await save({ orders: local } as Record<string, unknown>);
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
      title="Orders"
      subtitle="Order placement settings. These values are read by the bot but have no effect until Phase 8 (live order placement) is enabled."
      onSave={handleSave}
      isDirty={isDirty}
      onReload={handleReload}
    >
      {/* Phase 8 banner */}
      <div className="py-3">
        <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
          <span className="mt-0.5 shrink-0 rounded bg-amber-200 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-amber-800">
            Phase 8 only
          </span>
          <p className="text-xs text-amber-800">
            These settings are <span className="font-semibold">ignored in alert-only and paper-trade mode</span>.
            They take effect only when <code className="rounded bg-amber-100 px-1 font-mono">order_place_mode: ON</code> is
            set (Phase 8), which requires a bot restart.
          </p>
        </div>
      </div>

      <SelectField
        label="Order Type"
        helper="Limit = place at the exact entry price; Market = fill immediately at the best available price."
        value={local.order_type}
        options={ORDER_TYPE_OPTIONS}
        onChange={(v) => set({ order_type: v })}
      />
      <Toggle
        label="Cancel If Price Touches TP1"
        helper="ON = if an unfilled limit order's price reaches TP1, cancel it (the move has already happened)."
        value={local.cancel_if_price_touches_tp1}
        onChange={(v) => set({ cancel_if_price_touches_tp1: v })}
      />
      <Toggle
        label="Fallback to Market If Limit Disabled"
        helper="ON = if limit orders are not available on this strike, fall back to a market order automatically."
        value={local.fallback_to_market_if_limit_disabled}
        onChange={(v) => set({ fallback_to_market_if_limit_disabled: v })}
      />
    </SectionShell>
  );
}
