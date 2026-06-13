import { useEffect, useMemo, useState } from "react";
import { useConfig } from "../../../context/ConfigContext";
import { useToast } from "../../../context/ToastContext";
import { SectionShell, Toggle } from "../index";

type TelegramLocal = {
  send_signal_alerts: boolean;
  send_rejection_alerts: boolean;
  send_eod_summary: boolean;
  send_circuit_breaker_alerts: boolean;
  send_startup_alert: boolean;
};

function fromConfig(config: Record<string, unknown> | null): TelegramLocal {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const t: any = (config as any)?.telegram ?? {};
  return {
    send_signal_alerts:          t.send_signal_alerts          ?? true,
    send_rejection_alerts:       t.send_rejection_alerts       ?? false,
    send_eod_summary:            t.send_eod_summary            ?? true,
    send_circuit_breaker_alerts: t.send_circuit_breaker_alerts ?? true,
    send_startup_alert:          t.send_startup_alert          ?? true,
  };
}

export function AlertsTelegramSection() {
  const { config, save, reload } = useConfig();
  const toast = useToast();
  const [local, setLocal] = useState<TelegramLocal>(() => fromConfig(config));

  useEffect(() => {
    setLocal(fromConfig(config));
  }, [config]);

  const remote = useMemo(() => fromConfig(config), [config]);
  const isDirty = JSON.stringify(local) !== JSON.stringify(remote);

  const set = (patch: Partial<TelegramLocal>) =>
    setLocal((prev) => ({ ...prev, ...patch }));

  const handleSave = async () => {
    const result = await save({ telegram: local } as Record<string, unknown>);
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
      title="Alerts & Telegram"
      subtitle="Choose which events the bot sends to your Telegram chat."
      onSave={handleSave}
      isDirty={isDirty}
      onReload={handleReload}
    >
      <Toggle
        label="Signal Alerts"
        helper="The main alert when all conditions pass (C1–C4, plus C5 if gating is ON)."
        value={local.send_signal_alerts}
        onChange={(v) => set({ send_signal_alerts: v })}
      />
      <Toggle
        label="Rejection Alerts"
        helper="Verbose / debugging — also send when conditions fail. Generates a lot of messages during active sessions."
        value={local.send_rejection_alerts}
        onChange={(v) => set({ send_rejection_alerts: v })}
      />
      <Toggle
        label="EOD Summary"
        helper="End-of-day summary sent at 3:30 PM IST with the day's signal and trade count."
        value={local.send_eod_summary}
        onChange={(v) => set({ send_eod_summary: v })}
      />
      <Toggle
        label="Circuit Breaker Alerts"
        helper="Alert when the daily SL count or daily loss cap is triggered and the bot stops for the day."
        value={local.send_circuit_breaker_alerts}
        onChange={(v) => set({ send_circuit_breaker_alerts: v })}
      />
      <Toggle
        label="Startup Alert"
        helper="Alert when the bot starts each morning, including the current config summary and active broker."
        value={local.send_startup_alert}
        onChange={(v) => set({ send_startup_alert: v })}
      />
    </SectionShell>
  );
}
