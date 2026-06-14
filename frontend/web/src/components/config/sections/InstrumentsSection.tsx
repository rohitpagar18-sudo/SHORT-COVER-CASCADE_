import { useEffect, useState } from "react";
import { useConfig } from "../../../context/ConfigContext";
import { SectionShell, Toggle } from "../index";

type InstrumentsLocal = {
  nifty_enabled: boolean;
  banknifty_enabled: boolean;
};

function fromConfig(config: Record<string, unknown> | null): InstrumentsLocal {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const i: any = (config as any)?.instruments ?? {};
  return {
    nifty_enabled: i.nifty_enabled ?? true,
    banknifty_enabled: i.banknifty_enabled ?? true,
  };
}

function LotSizeDisplay({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="flex flex-col gap-1 py-3 border-b border-line2 last:border-0">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-fg1">{label}</span>
        <span className="text-sm font-mono text-fg1 bg-bg2 border border-line2 rounded px-2 py-0.5 select-none">
          {value ?? "—"} units
        </span>
      </div>
      <p className="text-xs text-fg3">Auto-verified from broker at 09:15 IST</p>
    </div>
  );
}

export function InstrumentsSection() {
  const { config, save, reload } = useConfig();
  const [local, setLocal] = useState<InstrumentsLocal>(() => fromConfig(config));

  useEffect(() => {
    setLocal(fromConfig(config));
  }, [config]);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const instruments: any = (config as any)?.instruments ?? {};
  const niftyLotSize: number | null = instruments.nifty_lot_size ?? null;
  const bankniftyLotSize: number | null = instruments.banknifty_lot_size ?? null;

  const remote = fromConfig(config);
  const isDirty = JSON.stringify(local) !== JSON.stringify(remote);

  const set = (patch: Partial<InstrumentsLocal>) =>
    setLocal((prev) => ({ ...prev, ...patch }));

  const handleSave = () =>
    save({ instruments: local } as Record<string, unknown>);

  const handleReload = () => {
    setLocal(remote);
    reload();
  };

  return (
    <SectionShell
      title="Instruments"
      subtitle="Which underlyings the bot watches. Lot sizes are read from config and auto-verified against the broker at 09:15 IST."
      onSave={handleSave}
      isDirty={isDirty}
      onReload={handleReload}
    >
      <Toggle
        label="NIFTY Enabled"
        helper="Scan NIFTY options on every 5-min candle close"
        value={local.nifty_enabled}
        onChange={(v) => set({ nifty_enabled: v })}
      />
      <LotSizeDisplay label="NIFTY Lot Size" value={niftyLotSize} />
      <Toggle
        label="BankNifty Enabled"
        helper="Scan BankNifty options on every 5-min candle close"
        value={local.banknifty_enabled}
        onChange={(v) => set({ banknifty_enabled: v })}
      />
      <LotSizeDisplay label="BankNifty Lot Size" value={bankniftyLotSize} />
    </SectionShell>
  );
}
