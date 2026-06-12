interface NumberFieldProps {
  label: string;
  helper?: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
  prefix?: string;
  suffix?: string;
}

export function NumberField({
  label, helper, value, onChange, min, max, step = 1, disabled, prefix, suffix,
}: NumberFieldProps) {
  return (
    <div className="py-3">
      <label className="text-sm font-medium text-ink">{label}</label>
      {helper && <div className="mt-0.5 text-xs text-muted">{helper}</div>}
      <div className="mt-2 flex items-center gap-2">
        {prefix && <span className="text-sm text-muted">{prefix}</span>}
        <input
          type="number"
          value={value}
          min={min}
          max={max}
          step={step}
          disabled={disabled}
          onChange={(e) => {
            const n = Number(e.target.value);
            if (!Number.isNaN(n)) onChange(n);
          }}
          className="w-32 rounded-md border border-slate-300 px-2.5 py-1.5 text-sm text-ink
            focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500
            disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-muted"
        />
        {suffix && <span className="text-sm text-muted">{suffix}</span>}
      </div>
    </div>
  );
}
