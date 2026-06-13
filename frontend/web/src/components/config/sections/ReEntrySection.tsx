import { useEffect, useMemo, useState } from "react";
import { useConfig } from "../../../context/ConfigContext";
import { useToast } from "../../../context/ToastContext";
import { SectionShell, Toggle, NumberField } from "../index";

type ReEntryLocal = {
  cooldown_minutes_after_sl: number;
  same_strike_kill_after_2_sl: boolean;
};

function fromConfig(config: Record<string, unknown> | null): ReEntryLocal {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const r: any = (config as any)?.re_entry ?? {};
  return {
    cooldown_minutes_after_sl:  r.cooldown_minutes_after_sl  ?? 15,
    same_strike_kill_after_2_sl: r.same_strike_kill_after_2_sl ?? true,
  };
}

export function ReEntrySection() {
  const { config, save, reload } = useConfig();
  const toast = useToast();
  const [local, setLocal] = useState<ReEntryLocal>(() => fromConfig(config));

  useEffect(() => {
    setLocal(fromConfig(config));
  }, [config]);

  const remote = useMemo(() => fromConfig(config), [config]);
  const isDirty = JSON.stringify(local) !== JSON.stringify(remote);

  const handleSave = async () => {
    const result = await save({ re_entry: local } as Record<string, unknown>);
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
      title="Re-entry Rules"
      subtitle="Controls how quickly the bot can re-enter after a stop-loss, and whether repeatedly-SL'd strikes are blocked for the day."
      onSave={handleSave}
      isDirty={isDirty}
      onReload={handleReload}
    >
      <NumberField
        label="Cooldown Minutes After SL"
        helper="Wait at least this many minutes after any stop-loss before taking a new entry. 0 = no cooldown."
        value={local.cooldown_minutes_after_sl}
        min={0}
        suffix="min"
        onChange={(v) =>
          setLocal((prev) => ({ ...prev, cooldown_minutes_after_sl: v }))
        }
      />
      <Toggle
        label="Same Strike Kill After 2 SL"
        helper="ON = a strike that has been stopped out twice on the same day is blocked for the rest of that day."
        value={local.same_strike_kill_after_2_sl}
        onChange={(v) =>
          setLocal((prev) => ({ ...prev, same_strike_kill_after_2_sl: v }))
        }
      />
    </SectionShell>
  );
}
