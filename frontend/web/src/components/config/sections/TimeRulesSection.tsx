import { useEffect, useMemo, useState } from "react";
import { useConfig } from "../../../context/ConfigContext";
import { useToast } from "../../../context/ToastContext";
import { SectionShell, Toggle, NumberField, SelectField } from "../index";

const TIME_RE = /^([01]\d|2[0-3]):[0-5]\d$/;

type TimeFields = {
  normal_start_time: string;
  gap_day_start_time: string;
  last_entry_time: string;
  soft_squareoff_time: string;
  hard_squareoff_time: string;
};

type TimeRulesLocal = TimeFields & {
  gap_day_enabled: boolean;
  gap_day_threshold_pct: number;
  gap_day_direction: string;
};

const TIME_FIELD_LABELS: { key: keyof TimeFields; label: string; helper?: string }[] = [
  { key: "normal_start_time",   label: "Normal Start Time",   helper: "No new entries before this time on regular days." },
  { key: "gap_day_start_time",  label: "Gap Day Start Time",  helper: "On gap-up / gap-down days, wait until this time." },
  { key: "last_entry_time",     label: "Last Entry Time",     helper: "No new entries after this time." },
  { key: "soft_squareoff_time", label: "Soft Square-off Time", helper: "Start closing positions at this time." },
  {
    key: "hard_squareoff_time",
    label: "Hard Square-off Time",
    helper: "Hard close — enforced by the bot regardless of other settings.",
  },
];

function TimeInput({
  label, helper, value, onChange,
}: {
  label: string;
  helper?: string;
  value: string;
  onChange: (v: string) => void;
}) {
  const isValid = TIME_RE.test(value);
  return (
    <div className="py-3">
      <label className="text-sm font-medium text-ink">{label}</label>
      {helper && <div className="mt-0.5 text-xs text-muted">{helper}</div>}
      <div className="mt-2">
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="HH:MM"
          maxLength={5}
          className={[
            "w-28 rounded-md border px-2.5 py-1.5 text-sm font-mono text-ink",
            "focus:outline-none focus:ring-1",
            isValid
              ? "border-slate-300 focus:border-emerald-500 focus:ring-emerald-500"
              : "border-rose-400 bg-rose-50 focus:border-rose-400 focus:ring-rose-300",
          ].join(" ")}
        />
        {!isValid && (
          <div className="mt-1 text-xs text-rose-600">
            Use 24-hour format HH:MM (e.g. 09:45)
          </div>
        )}
      </div>
    </div>
  );
}

function CardHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="border-b border-slate-200 px-4 py-3">
      <div className="text-sm font-semibold text-ink">{title}</div>
      {subtitle && <div className="mt-0.5 text-xs text-muted">{subtitle}</div>}
    </div>
  );
}

function fromConfig(config: Record<string, unknown> | null): TimeRulesLocal {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const t: any = (config as any)?.time_rules ?? {};
  return {
    normal_start_time:   t.normal_start_time   ?? "09:45",
    gap_day_start_time:  t.gap_day_start_time  ?? "10:00",
    last_entry_time:     t.last_entry_time     ?? "14:30",
    soft_squareoff_time: t.soft_squareoff_time ?? "14:59",
    hard_squareoff_time: t.hard_squareoff_time ?? "15:00",
    gap_day_enabled:         t.gap_day_enabled         ?? false,
    gap_day_threshold_pct:   t.gap_day_threshold_pct   ?? 1.0,
    gap_day_direction:       t.gap_day_direction        ?? "both",
  };
}

const GAP_DIR_OPTIONS = [
  { value: "both", label: "Both (up & down)" },
  { value: "up",   label: "Up only" },
  { value: "down", label: "Down only" },
];

export function TimeRulesSection() {
  const { config, save, reload } = useConfig();
  const toast = useToast();
  const [local, setLocal] = useState<TimeRulesLocal>(() => fromConfig(config));

  useEffect(() => {
    setLocal(fromConfig(config));
  }, [config]);

  const remote = useMemo(() => fromConfig(config), [config]);
  const isDirty = JSON.stringify(local) !== JSON.stringify(remote);

  const allTimesValid = TIME_FIELD_LABELS.every(({ key }) => TIME_RE.test(local[key]));

  const setField = <K extends keyof TimeRulesLocal>(k: K, v: TimeRulesLocal[K]) =>
    setLocal((prev) => ({ ...prev, [k]: v }));

  const handleSave = async () => {
    const result = await save({ time_rules: local } as Record<string, unknown>);
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
      title="Time Rules"
      subtitle="Session boundaries and the gap-day rule. All times are IST (Asia/Kolkata)."
      onSave={handleSave}
      isDirty={isDirty}
      onReload={handleReload}
      saveDisabled={!allTimesValid}
      saveDisabledHint="Fix invalid time values before saving"
    >
      {/* Session Times */}
      <div className="py-3">
        <div className="rounded-lg border border-slate-200 bg-white">
          <CardHeader
            title="Session Times"
            subtitle="24-hour HH:MM format. Hard square-off is enforced in code and cannot be disabled."
          />
          <div className="divide-y divide-slate-100 px-4">
            {TIME_FIELD_LABELS.map(({ key, label, helper }) => (
              <TimeInput
                key={key}
                label={label}
                helper={helper}
                value={local[key]}
                onChange={(v) => setField(key, v)}
              />
            ))}
          </div>
        </div>
      </div>

      {/* Gap Day Rule */}
      <div className="py-3">
        <div className="rounded-lg border border-slate-200 bg-white">
          <CardHeader
            title="Gap Day Rule"
            subtitle="Delays the start time when the market opens more than the threshold % from the previous close. VWAP is distorted by large opening candles on gap days."
          />
          <div className="divide-y divide-slate-100 px-4">
            <Toggle
              label="Gap Day Enabled"
              helper="When OFF: gap math is still computed and logged for analysis, but the Normal Start Time is always used."
              value={local.gap_day_enabled}
              onChange={(v) => setField("gap_day_enabled", v)}
            />
            <NumberField
              label="Gap Day Threshold (%)"
              helper="% move from previous close that qualifies as a gap day. 1.0 = strategy default."
              value={local.gap_day_threshold_pct}
              min={0}
              step={0.1}
              suffix="%"
              onChange={(v) => setField("gap_day_threshold_pct", v)}
            />
            <SelectField
              label="Gap Day Direction"
              helper="Which gap direction triggers the delayed start."
              value={local.gap_day_direction}
              options={GAP_DIR_OPTIONS}
              onChange={(v) => setField("gap_day_direction", v)}
            />
          </div>
        </div>
      </div>
    </SectionShell>
  );
}
