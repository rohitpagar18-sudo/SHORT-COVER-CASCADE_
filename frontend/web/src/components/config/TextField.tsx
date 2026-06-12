interface TextFieldProps {
  label: string;
  helper?: string;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export function TextField({ label, helper, value, onChange, disabled, placeholder }: TextFieldProps) {
  return (
    <div className="py-3">
      <label className="text-sm font-medium text-ink">{label}</label>
      {helper && <div className="mt-0.5 text-xs text-muted">{helper}</div>}
      <input
        type="text"
        value={value}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="mt-2 w-full max-w-xs rounded-md border border-slate-300 px-2.5 py-1.5 text-sm text-ink
          focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500
          disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-muted"
      />
    </div>
  );
}
