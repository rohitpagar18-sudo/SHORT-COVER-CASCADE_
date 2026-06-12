interface RadioCardsProps {
  label: string;
  helper?: string;
  value: string;
  options: { value: string; label: string; description?: string }[];
  onChange: (v: string) => void;
  disabled?: boolean;
}

export function RadioCards({
  label, helper, value, options, onChange, disabled,
}: RadioCardsProps) {
  return (
    <div className="py-3">
      <div className="text-sm font-medium text-ink">{label}</div>
      {helper && <div className="mt-0.5 text-xs text-muted">{helper}</div>}
      <div className="mt-2 flex flex-wrap gap-3">
        {options.map((o) => {
          const selected = value === o.value;
          return (
            <button
              key={o.value}
              type="button"
              disabled={disabled}
              onClick={() => onChange(o.value)}
              className={[
                "min-w-[140px] flex-1 rounded-lg border-2 px-4 py-3 text-left transition-colors",
                "focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-1",
                disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer",
                selected
                  ? "border-emerald-500 bg-emerald-50"
                  : "border-slate-200 bg-white hover:border-slate-300",
              ].join(" ")}
            >
              <div
                className={`text-sm font-semibold ${selected ? "text-emerald-700" : "text-ink"}`}
              >
                {o.label}
              </div>
              {o.description && (
                <div className="mt-0.5 text-xs text-muted">{o.description}</div>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
