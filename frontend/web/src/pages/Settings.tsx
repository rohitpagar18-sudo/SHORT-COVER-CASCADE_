import { Info, Moon, RotateCcw, Settings as SettingsIcon, Sun } from "lucide-react";
import { Card, CardTitle } from "../components/Card";
import { useTheme } from "../context/ThemeContext";
import { useToast } from "../context/ToastContext";
import {
  DEFAULT_SETTINGS,
  useSettings,
  type CurrencyDisplay,
  type DateRangePreset,
  type PollInterval,
} from "../context/SettingsContext";

const DATE_RANGES: DateRangePreset[] = ["This Week", "This Month", "This Quarter"];
const POLL_INTERVALS: PollInterval[] = [10, 15, 30, 60];
const CURRENCY_OPTIONS: CurrencyDisplay[] = ["₹", "INR"];

export default function SettingsPage() {
  const { settings, update, reset } = useSettings();
  const { theme, setTheme } = useTheme();
  const toast = useToast();

  const onReset = () => {
    reset();
    setTheme("light");
    toast.push("Dashboard settings reset to defaults", "info");
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardTitle>
          <span className="flex items-center gap-2">
            <SettingsIcon className="h-4 w-4 text-emerald-500" />
            Dashboard Settings
          </span>
        </CardTitle>
        <div className="flex items-start gap-2 rounded-md border border-sky-300 bg-sky-50 px-3 py-2 text-xs text-sky-700 dark:border-sky-900 dark:bg-sky-950/40 dark:text-sky-200">
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            These settings control the dashboard UI only — they do{" "}
            <span className="font-semibold">not</span> change the bot's config. Bot behavior is
            edited from the Configuration pages (which write{" "}
            <code className="font-mono">config.yaml</code>).
          </div>
        </div>
      </Card>

      <Card>
        <CardTitle>Theme</CardTitle>
        <div className="grid grid-cols-2 gap-2">
          <ToggleButton
            active={theme === "light"}
            onClick={() => setTheme("light")}
            icon={<Sun className="h-4 w-4" />}
            label="Light"
          />
          <ToggleButton
            active={theme === "dark"}
            onClick={() => setTheme("dark")}
            icon={<Moon className="h-4 w-4" />}
            label="Dark"
          />
        </div>
        <p className="mt-2 text-[11px] text-muted">
          Synced with the toggle in the sidebar footer. Stored in localStorage under{" "}
          <code className="font-mono">scc.theme</code>.
        </p>
      </Card>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card>
          <CardTitle>Default Date Range</CardTitle>
          <div className="grid grid-cols-3 gap-2">
            {DATE_RANGES.map((d) => (
              <ToggleButton
                key={d}
                active={settings.defaultDateRange === d}
                onClick={() => update("defaultDateRange", d)}
                label={d}
              />
            ))}
          </div>
          <p className="mt-2 text-[11px] text-muted">
            Used across Trades & Performance and Dashboard & Reports when no explicit range is set.
          </p>
        </Card>

        <Card>
          <CardTitle>Refresh / Poll Interval</CardTitle>
          <div className="grid grid-cols-4 gap-2">
            {POLL_INTERVALS.map((n) => (
              <ToggleButton
                key={n}
                active={settings.pollIntervalSeconds === n}
                onClick={() => update("pollIntervalSeconds", n)}
                label={`${n}s`}
              />
            ))}
          </div>
          <p className="mt-2 text-[11px] text-muted">
            Applies to live pages (Bot Status, Logs Viewer, Open Positions). The bot itself scans
            every 5 min — polling more often just keeps the UI fresh.
          </p>
        </Card>
      </div>

      <Card>
        <CardTitle>Currency Display</CardTitle>
        <div className="grid grid-cols-2 gap-2">
          {CURRENCY_OPTIONS.map((c) => (
            <ToggleButton
              key={c}
              active={settings.currencyDisplay === c}
              onClick={() => update("currencyDisplay", c)}
              label={c === "₹" ? "Symbol (₹)" : "Code (INR)"}
            />
          ))}
        </div>
        <div className="mt-3 flex items-center gap-2 text-sm">
          <input
            id="compactNumbers"
            type="checkbox"
            checked={settings.compactNumbers}
            onChange={(e) => update("compactNumbers", e.target.checked)}
            className="h-4 w-4 rounded border-line"
          />
          <label htmlFor="compactNumbers" className="text-ink">
            Compact large numbers (e.g. 12.4K, 3.5L)
          </label>
        </div>
      </Card>

      <Card>
        <CardTitle>Reset</CardTitle>
        <button
          onClick={onReset}
          className="flex items-center gap-2 rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-700 hover:bg-rose-100 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300"
        >
          <RotateCcw className="h-4 w-4" />
          Reset dashboard settings to defaults
        </button>
        <p className="mt-2 text-[11px] text-muted">
          Restores theme = Light, date range = {DEFAULT_SETTINGS.defaultDateRange}, poll ={" "}
          {DEFAULT_SETTINGS.pollIntervalSeconds}s. Does not touch{" "}
          <code className="font-mono">config.yaml</code> or any bot file.
        </p>
      </Card>
    </div>
  );
}

function ToggleButton({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon?: React.ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "flex items-center justify-center gap-1.5 rounded-md border px-3 py-2 text-sm",
        active
          ? "border-emerald-400 bg-emerald-50 text-emerald-700 dark:border-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
          : "border-line bg-card text-ink hover:bg-line2",
      ].join(" ")}
    >
      {icon}
      {label}
    </button>
  );
}
