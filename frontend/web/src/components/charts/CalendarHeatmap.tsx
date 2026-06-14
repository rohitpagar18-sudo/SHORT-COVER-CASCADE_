import { useState } from "react";

// CalendarDay type is defined here and re-exported so consumers can use it
export type CalendarDay = { date: string; pnl: number; trades: number };

type TooltipState = { x: number; y: number; day: CalendarDay } | null;

// Day-of-week headers starting Monday
const DOW_HEADERS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function getMonthKey(dateStr: string): string {
  return dateStr.slice(0, 7); // "YYYY-MM"
}

function formatMonthLabel(monthKey: string): string {
  const [year, month] = monthKey.split("-");
  const date = new Date(Number(year), Number(month) - 1, 1);
  return date.toLocaleString("en-IN", { month: "long", year: "numeric" });
}

// Returns ISO weekday index 0=Mon … 6=Sun for a date string "YYYY-MM-DD"
function isoWeekday(dateStr: string): number {
  const d = new Date(dateStr + "T00:00:00");
  // getDay() returns 0=Sun..6=Sat; shift to 0=Mon..6=Sun
  return (d.getDay() + 6) % 7;
}

function getDayNumber(dateStr: string): number {
  return new Date(dateStr + "T00:00:00").getDate();
}

// Builds weeks array for a month: each week is a 7-element array (Mon-Sun)
// with null for days outside the month.
function buildMonthWeeks(days: CalendarDay[]): (CalendarDay | null)[][] {
  if (days.length === 0) return [];

  // Build a quick lookup by date string
  const byDate = new Map<string, CalendarDay>();
  for (const d of days) byDate.set(d.date, d);

  // Find first and last calendar date of the month
  const sorted = [...days].sort((a, b) => a.date.localeCompare(b.date));
  const firstDate = sorted[0].date;
  const [year, month] = firstDate.split("-").map(Number);
  const daysInMonth = new Date(year, month, 0).getDate();

  // Build all dates in month
  const allDates: string[] = [];
  for (let d = 1; d <= daysInMonth; d++) {
    const dd = String(d).padStart(2, "0");
    const mm = String(month).padStart(2, "0");
    allDates.push(`${year}-${mm}-${dd}`);
  }

  const weeks: (CalendarDay | null)[][] = [];
  let currentWeek: (CalendarDay | null)[] = new Array(7).fill(null);

  for (const dateStr of allDates) {
    const dow = isoWeekday(dateStr);
    if (dow === 0 && currentWeek.some((x) => x !== null)) {
      weeks.push(currentWeek);
      currentWeek = new Array(7).fill(null);
    }
    // Use the actual data point if present, or a placeholder with 0 trades
    // so we know the day number to render
    currentWeek[dow] = byDate.get(dateStr) ?? { date: dateStr, pnl: 0, trades: 0 };
  }
  if (currentWeek.some((x) => x !== null)) {
    weeks.push(currentWeek);
  }

  return weeks;
}

type CellColorClass = string;

function getCellColorClass(day: CalendarDay | null, maxAbsPnl: number): CellColorClass {
  if (!day || day.trades === 0) return "";

  const abs = Math.abs(day.pnl);
  const ratio = maxAbsPnl > 0 ? abs / maxAbsPnl : 0;

  const level: "light" | "medium" | "dark" =
    ratio <= 0.33 ? "light" : ratio <= 0.67 ? "medium" : "dark";

  if (day.pnl > 0) {
    if (level === "light")
      return "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200";
    if (level === "medium")
      return "bg-emerald-300 text-emerald-900 dark:bg-emerald-700 dark:text-emerald-100";
    return "bg-emerald-500 text-white dark:bg-emerald-600";
  } else {
    // negative pnl
    if (level === "light")
      return "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200";
    if (level === "medium")
      return "bg-rose-300 text-rose-900 dark:bg-rose-700 dark:text-rose-100";
    return "bg-rose-500 text-white dark:bg-rose-600";
  }
}

function formatInr(amount: number): string {
  const abs = Math.abs(amount);
  const prefix = amount < 0 ? "-" : "+";
  if (abs >= 100_000) {
    return `${prefix}₹${(abs / 100_000).toFixed(2)}L`;
  }
  if (abs >= 1_000) {
    return `${prefix}₹${(abs / 1_000).toFixed(1)}K`;
  }
  return `${prefix}₹${Math.round(abs)}`;
}

type Props = { data: CalendarDay[] };

export default function CalendarHeatmap({ data }: Props) {
  const [tooltip, setTooltip] = useState<TooltipState>(null);

  if (data.length === 0) {
    return (
      <div className="flex h-[160px] items-center justify-center text-sm text-muted">
        No data for this period.
      </div>
    );
  }

  // Compute max absolute P&L across the entire dataset for colour scaling
  const maxAbsPnl = Math.max(...data.map((d) => Math.abs(d.pnl)), 1);

  // Group by month key
  const monthMap = new Map<string, CalendarDay[]>();
  for (const day of data) {
    const key = getMonthKey(day.date);
    if (!monthMap.has(key)) monthMap.set(key, []);
    monthMap.get(key)!.push(day);
  }

  // Sort months ascending
  const sortedMonthKeys = [...monthMap.keys()].sort();

  return (
    <div className="space-y-6">
      {sortedMonthKeys.map((monthKey) => {
        const monthDays = monthMap.get(monthKey)!;
        const weeks = buildMonthWeeks(monthDays);

        return (
          <div key={monthKey}>
            {/* Month heading */}
            <div className="mb-2 text-xs font-semibold text-ink">
              {formatMonthLabel(monthKey)}
            </div>

            {/* Calendar grid */}
            <div className="overflow-x-auto">
              <div style={{ minWidth: 280 }}>
                {/* Day-of-week header row */}
                <div className="grid grid-cols-7 gap-1 mb-1">
                  {DOW_HEADERS.map((h) => (
                    <div
                      key={h}
                      className="text-center text-[10px] uppercase tracking-wide text-muted select-none"
                    >
                      {h}
                    </div>
                  ))}
                </div>

                {/* Week rows */}
                {weeks.map((week, wi) => (
                  <div key={wi} className="grid grid-cols-7 gap-1 mb-1">
                    {week.map((cell, di) => {
                      if (!cell) {
                        // Empty cell (outside month boundary)
                        return <div key={di} className="h-10 rounded" />;
                      }

                      const colorCls = getCellColorClass(cell, maxAbsPnl);
                      const hasData = cell.trades > 0;

                      return (
                        <div
                          key={di}
                          className={`relative h-10 rounded flex flex-col items-center justify-center cursor-default select-none transition-opacity hover:opacity-80 ${
                            colorCls || "bg-slate-50 dark:bg-slate-800/40"
                          }`}
                          onMouseEnter={(e) => {
                            if (hasData) {
                              setTooltip({ x: e.clientX, y: e.clientY, day: cell });
                            }
                          }}
                          onMouseMove={(e) => {
                            if (hasData && tooltip) {
                              setTooltip({ x: e.clientX, y: e.clientY, day: cell });
                            }
                          }}
                          onMouseLeave={() => setTooltip(null)}
                        >
                          <span className="text-[11px] font-semibold leading-none">
                            {getDayNumber(cell.date)}
                          </span>
                          {hasData && (
                            <span className="mt-0.5 text-[9px] leading-none opacity-90">
                              {formatInr(cell.pnl)}
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                ))}
              </div>
            </div>
          </div>
        );
      })}

      {/* Tooltip */}
      {tooltip && (
        <div
          className="pointer-events-none fixed z-50 rounded-md border border-line bg-card px-3 py-2 shadow-lg text-xs"
          style={{ top: tooltip.y - 40, left: tooltip.x + 12 }}
        >
          <div className="font-semibold text-ink">{tooltip.day.date}</div>
          <div className={`mt-0.5 font-semibold ${tooltip.day.pnl >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}`}>
            {tooltip.day.pnl >= 0 ? "+" : ""}
            {new Intl.NumberFormat("en-IN", {
              style: "currency",
              currency: "INR",
              minimumFractionDigits: 0,
              maximumFractionDigits: 0,
            }).format(tooltip.day.pnl)}
          </div>
          <div className="mt-0.5 text-muted">{tooltip.day.trades} trade{tooltip.day.trades !== 1 ? "s" : ""}</div>
        </div>
      )}
    </div>
  );
}
