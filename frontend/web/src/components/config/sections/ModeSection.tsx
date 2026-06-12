import { useEffect, useState } from "react";
import { useConfig } from "../../../context/ConfigContext";
import { SectionShell, Toggle } from "../index";

type ModeLocal = {
  alert_mode: boolean;
  order_place_mode: boolean;
  paper_trade_mode: boolean;
};

function fromConfig(config: Record<string, unknown> | null): ModeLocal {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const m: any = (config as any)?.mode ?? {};
  return {
    alert_mode: m.alert_mode ?? true,
    order_place_mode: m.order_place_mode ?? false,
    paper_trade_mode: m.paper_trade_mode ?? true,
  };
}

export function ModeSection() {
  const { config, save, reload } = useConfig();
  const [local, setLocal] = useState<ModeLocal>(() => fromConfig(config));

  useEffect(() => {
    setLocal(fromConfig(config));
  }, [config]);

  const remote = fromConfig(config);
  const isDirty = JSON.stringify(local) !== JSON.stringify(remote);

  const set = (patch: Partial<ModeLocal>) =>
    setLocal((prev) => ({ ...prev, ...patch }));

  const handleSave = () =>
    save({ mode: local } as Record<string, unknown>);

  const handleReload = () => {
    setLocal(remote);
    reload();
  };

  return (
    <SectionShell
      title="Mode Controls"
      subtitle="Master switches. Changes to order_place_mode require a bot restart to take effect."
      onSave={handleSave}
      isDirty={isDirty}
      onReload={handleReload}
    >
      <Toggle
        label="Alert Mode"
        helper="ON = send Telegram alerts when all conditions (C0–C4) pass"
        value={local.alert_mode}
        onChange={(v) => set({ alert_mode: v })}
      />
      <Toggle
        label="Order Place Mode"
        helper="ON = place real broker orders (Phase 8 only). Requires bot restart."
        value={local.order_place_mode}
        onChange={(v) => set({ order_place_mode: v })}
      />
      <Toggle
        label="Paper Trade Mode"
        helper="ON = simulate trades in logs/paper_trades.jsonl — no real money"
        value={local.paper_trade_mode}
        onChange={(v) => set({ paper_trade_mode: v })}
      />
    </SectionShell>
  );
}
