import { Bell, Calendar, RefreshCw } from "lucide-react";
import { fmtClock, fmtDateLong } from "../lib/format";

type Props = {
  title: string;
  subtitle?: string;
  lastSynced?: string | null;
  lastConfigReload?: string | null;
  notificationCount?: number;
  selectedDate?: string;
  onSelectDate?: (d: string) => void;
  onReload?: () => void;
};

export default function Header({
  title,
  subtitle,
  lastSynced,
  lastConfigReload,
  notificationCount = 0,
  selectedDate,
  onSelectDate,
  onReload,
}: Props) {
  return (
    <header className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 border-b border-line bg-surface/95 px-6 py-3 backdrop-blur">
      <div>
        <h1 className="text-lg font-semibold text-ink">{title}</h1>
        {subtitle ? (
          <div className="text-xs text-muted">{subtitle}</div>
        ) : (
          <div className="text-xs text-muted">Auto-Reload: ON · polls every 15s</div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <div className="hidden items-center gap-1.5 rounded-md border border-line bg-card px-2.5 py-1.5 text-muted md:flex">
          <RefreshCw className="h-3.5 w-3.5" />
          <span>
            Last Config Reload: <span className="text-ink">{fmtClock(lastConfigReload)}</span>
          </span>
          <span className="mx-1.5 text-line">·</span>
          <span>Auto-Reload: <span className="text-emerald-600 dark:text-emerald-400">ON</span></span>
        </div>

        <button
          type="button"
          className="relative inline-flex items-center justify-center rounded-md border border-line bg-card p-2 text-muted hover:text-ink"
          title={`${notificationCount} alert${notificationCount === 1 ? "" : "s"} today`}
          aria-label="Notifications"
        >
          <Bell className="h-4 w-4" />
          {notificationCount > 0 && (
            <span className="absolute -right-1 -top-1 inline-flex h-4 min-w-[16px] items-center justify-center rounded-full bg-rose-500 px-1 text-[10px] font-medium text-white">
              {notificationCount > 99 ? "99+" : notificationCount}
            </span>
          )}
        </button>

        <label className="flex items-center gap-1.5 rounded-md border border-line bg-card px-2 py-1.5 text-ink">
          <Calendar className="h-3.5 w-3.5 text-muted" />
          <input
            type="date"
            value={selectedDate ?? ""}
            onChange={(e) => onSelectDate?.(e.target.value)}
            className="bg-transparent text-xs outline-none"
            aria-label="Date filter"
          />
          {selectedDate && (
            <span className="hidden text-[11px] text-muted lg:inline">
              {fmtDateLong(selectedDate)}
            </span>
          )}
        </label>

        <button
          type="button"
          onClick={onReload}
          className="inline-flex items-center gap-1.5 rounded-md border border-line bg-card px-2.5 py-1.5 text-ink hover:bg-line2"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Reload Config
        </button>

        <div className="hidden items-center gap-1.5 text-muted lg:flex">
          <span>Last synced:</span>
          <span className="text-ink">
            {lastSynced ? new Date(lastSynced).toLocaleTimeString("en-IN") : "—"}
          </span>
        </div>
      </div>
    </header>
  );
}
