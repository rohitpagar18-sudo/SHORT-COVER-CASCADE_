interface SelectFieldProps {
  label: string;
  helper?: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
  disabled?: boolean;
}

export function SelectField({ label, helper, value, options, onChange, disabled }: SelectFieldProps) {
  return (
    <div className="py-3">
      <label className="text-sm font-medium text-ink">{label}</label>
      {helper && <div className="mt-0.5 text-xs text-muted">{helper}</div>}
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="mt-2 w-48 rounded-md border border-slate-300 px-2.5 py-1.5 text-sm text-ink
          focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500
          disabled:cursor-not-allowed disabled:bg-slate-50"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  );
}
