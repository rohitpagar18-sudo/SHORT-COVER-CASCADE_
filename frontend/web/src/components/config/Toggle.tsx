interface ToggleProps {
  label: string;
  helper?: string;
  value: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}

export function Toggle({ label, helper, value, onChange, disabled }: ToggleProps) {
  return (
    <div className="flex items-center justify-between gap-4 py-3">
      <div className="min-w-0">
        <div className="text-sm font-medium text-ink">{label}</div>
        {helper && <div className="mt-0.5 text-xs text-muted">{helper}</div>}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <span className={`text-xs font-semibold ${value ? "text-emerald-600" : "text-slate-400"}`}>
          {value ? "ON" : "OFF"}
        </span>
        <button
          type="button"
          role="switch"
          aria-checked={value}
          disabled={disabled}
          onClick={() => onChange(!value)}
          className={[
            "relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent",
            "transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-1",
            disabled ? "cursor-not-allowed opacity-50" : "",
            value ? "bg-emerald-500" : "bg-slate-300",
          ].join(" ")}
        >
          <span
            className={[
              "pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0",
              "transition duration-200",
              value ? "translate-x-5" : "translate-x-0",
            ].join(" ")}
          />
        </button>
      </div>
    </div>
  );
}
