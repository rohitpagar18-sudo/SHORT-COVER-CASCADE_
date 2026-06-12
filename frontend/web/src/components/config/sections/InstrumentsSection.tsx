import { useEffect, useState } from "react";
import { useConfig } from "../../../context/ConfigContext";
import { SectionShell, Toggle, NumberField } from "../index";

type InstrumentsLocal = {
  nifty_enabled: boolean;
  banknifty_enabled: boolean;
  nifty_lot_size: number;
  banknifty_lot_size: number;
};

function fromConfig(config: Record<string, unknown> | null): InstrumentsLocal {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const i: any = (config as any)?.instruments ?? {};
  return {
    nifty_enabled: i.nifty_enabled ?? true,
    banknifty_enabled: i.banknifty_enabled ?? true,
    nifty_lot_size: i.nifty_lot_size ?? 75,
    banknifty_lot_size: i.banknifty_lot_size ?? 30,
  };
}

export function InstrumentsSection() {
  const { config, save, reload } = useConfig();
  const [local, setLocal] = useState<InstrumentsLocal>(() => fromConfig(config));

  useEffect(() => {
    setLocal(fromConfig(config));
  }, [config]);

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
      subtitle="Which underlyings the bot watches. Lot sizes are auto-verified against the broker at 9:15 AM."
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
      <NumberField
        label="NIFTY Lot Size"
        helper="Bot warns and uses broker value if mismatch detected at 9:15 AM"
        value={local.nifty_lot_size}
        min={1}
        onChange={(v) => set({ nifty_lot_size: v })}
        suffix="units"
      />
      <Toggle
        label="BankNifty Enabled"
        helper="Scan BankNifty options on every 5-min candle close"
        value={local.banknifty_enabled}
        onChange={(v) => set({ banknifty_enabled: v })}
      />
      <NumberField
        label="BankNifty Lot Size"
        helper="Bot warns and uses broker value if mismatch detected at 9:15 AM"
        value={local.banknifty_lot_size}
        min={1}
        onChange={(v) => set({ banknifty_lot_size: v })}
        suffix="units"
      />
    </SectionShell>
  );
}
