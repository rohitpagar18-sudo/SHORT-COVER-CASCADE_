import { useCallback, useEffect, useRef, useState } from "react";
import { Download, RefreshCw } from "lucide-react";
import { Card, CardTitle, Skeleton } from "../components/Card";
import PnLChart from "../components/charts/PnLChart";
import WeekdayBarChart from "../components/charts/WeekdayBarChart";
import SimpleDonut from "../components/charts/SimpleDonut";
import KpiSparkline from "../components/charts/KpiSparkline";
import Histogram from "../components/charts/Histogram";
import {
  api,
  type PerformanceReport,
  type ReportKpi,
  type ReportTopTrade,
  type ReportMonthly,
  type ReportDuration,
  type ConditionsReport,
  type RiskReport,
} from "../lib/api";
import { inr, inrSigned } from "../lib/format";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const POLL_MS = 60_000;

const OUTCOME_COLORS: Record<string, string> = {
  TP2_HIT: "#16A34A",
  TP1_HIT: "#65A30D",
  SL_HIT: "#DC2626",
  PARTIAL: "#F59E0B",
  WOULD_SKIP: "#94A3B8",
  Running: "#64748B",
};

const OUTCOME_LABELS: Record<string, string> = {
  TP2_HIT: "TP2 HIT",
  TP1_HIT: "TP1 HIT",
  SL_HIT: "SL HIT",
  PARTIAL: "PARTIAL",
  WOULD_SKIP: "SKIP",
  Running: "RUNNING",
  NO_DATA: "RUNNING",
};

const UNDERLYING_COLORS: Record<string, string> = {
  NIFTY: "#2563EB",
  BANKNIFTY: "#7C3AED",
};

// ---------------------------------------------------------------------------
// IST helpers
// ---------------------------------------------------------------------------

function nowISTHHMM(): string {
  const now = new Date();
  const ist = new Date(now.getTime() + (now.getTimezoneOffset() + 330) * 60_000);
  return ist.toTimeString().slice(0, 5);
}

function todayIST(): Date {
  const now = new Date();
  return new Date(now.getTime() + (now.getTimezoneOffset() + 330) * 60_000);
}

function toISO(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function startOfWeekMon(d: Date): Date {
  const out = new Date(d);
  const day = (out.getDay() + 6) % 7;
  out.setDate(out.getDate() - day);
  return out;
}

function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

function startOfQuarter(d: Date): Date {
  const qMonth = Math.floor(d.getMonth() / 3) * 3;
  return new Date(d.getFullYear(), qMonth, 1);
}

type DatePreset = "this_week" | "this_month" | "this_quarter" | "last_30" | "last_90" | "custom";

function applyPreset(preset: DatePreset): { from: string; to: string } {
  const t = todayIST();
  const today = toISO(t);
  switch (preset) {
    case "this_week":
      return { from: toISO(startOfWeekMon(t)), to: today };
    case "this_month":
      return { from: toISO(startOfMonth(t)), to: today };
    case "this_quarter":
      return { from: toISO(startOfQuarter(t)), to: today };
    case "last_30": {
      const d30 = new Date(t);
      d30.setDate(d30.getDate() - 29);
      return { from: toISO(d30), to: today };
    }
    case "last_90": {
      const d90 = new Date(t);
      d90.setDate(d90.getDate() - 89);
      return { from: toISO(d90), to: today };
    }
    default:
      return { from: toISO(startOfMonth(t)), to: today };
  }
}

const PRESET_LABELS: Record<DatePreset, string> = {
  this_week: "This Week",
  this_month: "This Month",
  this_quarter: "This Quarter",
  last_30: "Last 30 Days",
  last_90: "Last 90 Days",
  custom: "Custom",
};

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

type Tab = "performance" | "strategy" | "conditions" | "risk" | "monthly" | "health";

const TABS: { id: Tab; label: string }[] = [
  { id: "performance", label: "Performance Overview" },
  { id: "strategy", label: "Strategy Insights" },
  { id: "conditions", label: "Condition Analysis (C0–C5)" },
  { id: "risk", label: "Risk Analysis" },
  { id: "monthly", label: "Monthly Summary" },
  { id: "health", label: "System Health" },
];

// ---------------------------------------------------------------------------
// Outcome badge
// ---------------------------------------------------------------------------

function OutcomeBadge({ outcome }: { outcome: string | null }) {
  if (!outcome) return <span className="text-xs text-muted">—</span>;
  const label = OUTCOME_LABELS[outcome] ?? outcome;
  const color = OUTCOME_COLORS[outcome] ?? "#94A3B8";
  const isLight = outcome === "WOULD_SKIP";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold ${isLight ? "text-slate-700" : "text-white"}`}
      style={{ backgroundColor: color }}
    >
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Delta badge
// ---------------------------------------------------------------------------

function DeltaBadge({ delta }: { delta: number | null }) {
  if (delta == null) return null;
  const up = delta >= 0;
  return (
    <span
      className={`inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-semibold ${
        up
          ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
          : "bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300"
      }`}
    >
      {up ? "▲" : "▼"} {Math.abs(delta).toFixed(1)}%
    </span>
  );
}

// ---------------------------------------------------------------------------
// KPI card
// ---------------------------------------------------------------------------

type KpiCardProps = {
  label: string;
  kpi: ReportKpi | undefined;
  format?: "inr" | "pct" | "mult" | "count";
};

function formatKpiValue(value: number | null, format: KpiCardProps["format"]): string {
  if (value == null) return "—";
  switch (format) {
    case "inr":
      return inrSigned(value);
    case "pct":
      return `${value.toFixed(1)}%`;
    case "mult":
      return `${value.toFixed(2)}×`;
    default:
      return value.toLocaleString("en-IN");
  }
}

function KpiCard({ label, kpi, format = "inr" }: KpiCardProps) {
  const value = kpi?.value ?? null;
  const spark = kpi?.spark ?? [];
  const isPositive = value == null || value >= 0;

  const valueCls =
    format === "inr" || format === "mult" || format === "count"
      ? value == null
        ? "text-ink"
        : value >= 0
        ? "text-emerald-600 dark:text-emerald-400"
        : "text-rose-600 dark:text-rose-400"
      : "text-ink";

  return (
    <div className="rounded-xl border border-line bg-card p-4 shadow-card">
      <div className="text-[10px] uppercase tracking-wide text-muted">{label}</div>
      <div className={`mt-2 text-xl font-semibold ${valueCls}`}>
        {formatKpiValue(value, format)}
      </div>
      <div className="mt-2 flex items-center justify-between gap-2">
        <DeltaBadge delta={kpi?.delta_pct ?? null} />
        {spark.length >= 2 && (
          <KpiSparkline data={spark} positive={isPositive} />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skeleton KPI row
// ---------------------------------------------------------------------------

function KpiSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4 2xl:grid-cols-7">
      {Array.from({ length: 7 }).map((_, i) => (
        <div key={i} className="rounded-xl border border-line bg-card p-4">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="mt-3 h-6 w-28" />
          <Skeleton className="mt-2 h-3 w-16" />
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Top trades table
// ---------------------------------------------------------------------------

function TopTradesTable({ rows, emptyLabel }: { rows: ReportTopTrade[]; emptyLabel: string }) {
  if (rows.length === 0) {
    return (
      <div className="py-6 text-center text-sm text-muted">{emptyLabel}</div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-left text-[10px] uppercase text-muted">
          <tr className="border-b border-line">
            <th className="py-2 pr-3">Time</th>
            <th className="py-2 pr-3">Symbol</th>
            <th className="py-2 pr-3">Type</th>
            <th className="py-2 pr-3">Strike</th>
            <th className="py-2 pr-3">P&L</th>
            <th className="py-2">Outcome</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-line2 last:border-0">
              <td className="py-2 pr-3 font-mono">{r.time || "—"}</td>
              <td className="py-2 pr-3">{r.symbol || "—"}</td>
              <td className="py-2 pr-3">{r.option_type || "—"}</td>
              <td className="py-2 pr-3">
                {r.strike ?? "—"}
                {r.relation && (
                  <span className="ml-1 text-[10px] text-muted">({r.relation})</span>
                )}
              </td>
              <td
                className={`py-2 pr-3 font-semibold ${
                  r.pnl >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"
                }`}
              >
                {inrSigned(r.pnl)}
              </td>
              <td className="py-2">
                <OutcomeBadge outcome={r.outcome} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Monthly table
// ---------------------------------------------------------------------------

function MonthlyTable({ rows }: { rows: ReportMonthly[] }) {
  if (rows.length === 0) {
    return (
      <div className="py-6 text-center text-sm text-muted">No historical data.</div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-left text-[10px] uppercase text-muted">
          <tr className="border-b border-line">
            <th className="py-2 pr-3">Month</th>
            <th className="py-2 pr-3">Trades</th>
            <th className="py-2 pr-3">Win Rate</th>
            <th className="py-2 pr-3">Total P&L</th>
            <th className="py-2 pr-3">Realized</th>
            <th className="py-2 pr-3">Unrealized</th>
            <th className="py-2 pr-3">Prof. Factor</th>
            <th className="py-2 pr-3">Max Profit</th>
            <th className="py-2">Max Loss</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.month} className="border-b border-line2 last:border-0">
              <td className="py-2 pr-3 font-medium text-ink">{r.month}</td>
              <td className="py-2 pr-3 text-ink">{r.total_trades}</td>
              <td className="py-2 pr-3 text-ink">{r.win_rate.toFixed(1)}%</td>
              <td
                className={`py-2 pr-3 font-semibold ${
                  r.total_pnl >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"
                }`}
              >
                {inrSigned(r.total_pnl)}
              </td>
              <td
                className={`py-2 pr-3 ${
                  r.realized_pnl >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"
                }`}
              >
                {inrSigned(r.realized_pnl)}
              </td>
              <td className="py-2 pr-3 text-ink">{inrSigned(r.unrealized_pnl)}</td>
              <td className="py-2 pr-3 text-ink">
                {r.profit_factor != null ? `${r.profit_factor.toFixed(2)}×` : "—"}
              </td>
              <td className="py-2 pr-3 text-emerald-600 dark:text-emerald-400">
                {inr(r.max_profit)}
              </td>
              <td className="py-2 text-rose-600 dark:text-rose-400">
                {inr(Math.abs(r.max_loss))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Duration table
// ---------------------------------------------------------------------------

function DurationTable({ rows }: { rows: ReportDuration[] }) {
  if (rows.length === 0) {
    return (
      <div className="py-6 text-center text-sm text-muted">No duration data.</div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-left text-[10px] uppercase text-muted">
          <tr className="border-b border-line">
            <th className="py-2 pr-3">Duration</th>
            <th className="py-2 pr-3">Trades</th>
            <th className="py-2">Win Rate</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.bucket} className="border-b border-line2 last:border-0">
              <td className="py-2 pr-3 text-ink">{r.bucket}</td>
              <td className="py-2 pr-3 text-ink">{r.trades}</td>
              <td
                className={`py-2 font-semibold ${
                  r.win_rate >= 50 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"
                }`}
              >
                {r.win_rate.toFixed(1)}%
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Coming soon placeholder
// ---------------------------------------------------------------------------

function ComingSoonTab({ label }: { label: string }) {
  return (
    <div className="flex h-[40vh] items-center justify-center">
      <div className="text-center">
        <div className="text-4xl">🚧</div>
        <h3 className="mt-3 text-lg font-semibold text-ink">{label}</h3>
        <p className="mt-1 text-sm text-muted">Coming in a later phase.</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function DashboardReportsPage() {
  const [activeTab, setActiveTab] = useState<Tab>("performance");

  // Date range state
  const [preset, setPreset] = useState<DatePreset>("this_month");
  const initialRange = applyPreset("this_month");
  const [from, setFrom] = useState(initialRange.from);
  const [to, setTo] = useState(initialRange.to);

  // Applied range (what was last submitted)
  const [appliedFrom, setAppliedFrom] = useState(initialRange.from);
  const [appliedTo, setAppliedTo] = useState(initialRange.to);

  // Aggregation for cumulative chart
  const [agg, setAgg] = useState<"daily" | "weekly" | "monthly">("daily");

  // Data
  const [data, setData] = useState<PerformanceReport | null>(null);
  const [conditionsData, setConditionsData] = useState<ConditionsReport | null>(null);
  const [riskData, setRiskData] = useState<RiskReport | null>(null);
  const [stale, setStale] = useState(false);
  const [lastSynced, setLastSynced] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const aliveRef = useRef(true);
  const timerRef = useRef<number | undefined>(undefined);

  const fetchData = useCallback(
    async (df: string, dt: string, ag: string) => {
      try {
        const [perfResult, condResult, riskResult] = await Promise.all([
          api.reportsPerformance({ date_from: df, date_to: dt, agg: ag }),
          api.reportsConditions({ date_from: df, date_to: dt }),
          api.reportsRisk({ date_from: df, date_to: dt }),
        ]);
        if (!aliveRef.current) return;
        setData(perfResult);
        setConditionsData(condResult);
        setRiskData(riskResult);
        setStale(false);
        setLastSynced(nowISTHHMM());
      } catch {
        if (!aliveRef.current) return;
        // Keep last good data; mark stale
        setStale(true);
      } finally {
        if (aliveRef.current) setLoading(false);
      }
    },
    [],
  );

  // Initial load + polling
  useEffect(() => {
    aliveRef.current = true;
    setLoading(true);

    const tick = async () => {
      await fetchData(appliedFrom, appliedTo, agg);
      if (aliveRef.current) {
        timerRef.current = window.setTimeout(tick, POLL_MS);
      }
    };
    tick();
    return () => {
      aliveRef.current = false;
      if (timerRef.current) window.clearTimeout(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appliedFrom, appliedTo, agg]);

  const onPickPreset = useCallback((p: DatePreset) => {
    setPreset(p);
    if (p !== "custom") {
      const r = applyPreset(p);
      setFrom(r.from);
      setTo(r.to);
    }
  }, []);

  const onApply = useCallback(() => {
    setAppliedFrom(from);
    setAppliedTo(to);
    setLoading(true);
  }, [from, to]);

  const onRefresh = useCallback(() => {
    setLoading(true);
    if (timerRef.current) window.clearTimeout(timerRef.current);
    fetchData(appliedFrom, appliedTo, agg);
  }, [appliedFrom, appliedTo, agg, fetchData]);

  // Derived: build donut items for underlying
  const underlyingItems = (data?.pnl_by_underlying ?? []).map((u) => ({
    name: u.symbol,
    value: Math.round(Math.abs(u.pnl)),
    pct: u.pct,
    color: UNDERLYING_COLORS[u.symbol] ?? "#6B7280",
  }));

  // Derived: build donut items for outcome distribution
  const outcomeItems = (data?.outcome_distribution ?? []).map((o) => ({
    name: OUTCOME_LABELS[o.outcome] ?? o.outcome,
    value: o.count,
    pct: o.pct,
    color: OUTCOME_COLORS[o.outcome] ?? "#94A3B8",
  }));

  // Derived: map cumulative to PnLChart shape
  const pnlDays = (data?.cumulative ?? []).map((p) => ({
    date: p.period,
    realized_pnl: p.daily_pnl,
    is_profit: p.daily_pnl >= 0,
  }));
  const cumulativePoints = (data?.cumulative ?? []).map((p) => ({
    date: p.period,
    net: p.cumulative_pnl,
  }));

  return (
    <div className="space-y-4">
      {/* ---- Page header ---- */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-bold text-ink">Dashboard &amp; Reports</h2>
          <p className="text-xs text-muted">
            Performance analytics for paper trading. All times IST.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {lastSynced && (
            <span className="flex items-center gap-1 text-xs text-muted">
              <RefreshCw className="h-3 w-3" />
              Last synced {lastSynced}
            </span>
          )}
          <button
            onClick={onRefresh}
            className="flex items-center gap-1.5 rounded-md border border-line bg-card px-2.5 py-1.5 text-xs text-ink hover:bg-line2"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
          <button
            disabled
            title="Coming soon"
            className="flex items-center gap-1.5 rounded-md border border-line bg-card px-2.5 py-1.5 text-xs text-muted opacity-50 cursor-not-allowed"
          >
            <Download className="h-3.5 w-3.5" />
            Export
          </button>
        </div>
      </div>

      {/* ---- Date range bar ---- */}
      <Card>
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <div className="mb-1 text-[10px] uppercase tracking-wide text-muted">Date Range</div>
            <div className="flex flex-wrap gap-1">
              {(Object.keys(PRESET_LABELS) as DatePreset[]).map((p) => (
                <button
                  key={p}
                  onClick={() => onPickPreset(p)}
                  className={`rounded-md border px-2 py-1 text-xs ${
                    preset === p
                      ? "border-emerald-400 bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
                      : "border-line bg-card text-ink hover:bg-line2"
                  }`}
                >
                  {PRESET_LABELS[p]}
                </button>
              ))}
            </div>
          </div>
          {preset === "custom" && (
            <>
              <div>
                <div className="mb-1 text-[10px] uppercase tracking-wide text-muted">From</div>
                <input
                  type="date"
                  value={from}
                  onChange={(e) => { setFrom(e.target.value); setPreset("custom"); }}
                  className="rounded-md border border-line bg-card px-2 py-1 text-sm text-ink"
                />
              </div>
              <div>
                <div className="mb-1 text-[10px] uppercase tracking-wide text-muted">To</div>
                <input
                  type="date"
                  value={to}
                  onChange={(e) => { setTo(e.target.value); setPreset("custom"); }}
                  className="rounded-md border border-line bg-card px-2 py-1 text-sm text-ink"
                />
              </div>
            </>
          )}
          <button
            onClick={onApply}
            className="rounded-md border border-emerald-500 bg-emerald-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-600"
          >
            Apply
          </button>
        </div>
      </Card>

      {/* ---- Stale banner ---- */}
      {stale && (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
          Showing last known data — refresh failed. Will retry automatically.
        </div>
      )}

      {/* ---- Tab bar ---- */}
      <div className="border-b border-line">
        <div className="flex flex-wrap gap-0">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px ${
                activeTab === tab.id
                  ? "border-emerald-500 text-emerald-600 dark:text-emerald-400"
                  : "border-transparent text-muted hover:text-ink"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* ---- Tab content ---- */}
      {activeTab === "performance" && (
        <div className="space-y-4">
          {/* 1. KPI row */}
          {loading && !data ? (
            <KpiSkeleton />
          ) : (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4 2xl:grid-cols-7">
              <KpiCard label="Total P&L" kpi={data?.kpis.total_pnl} format="inr" />
              <KpiCard label="Total Trades" kpi={data?.kpis.total_trades} format="count" />
              <KpiCard label="Win Rate" kpi={data?.kpis.win_rate} format="pct" />
              <KpiCard label="Profit Factor" kpi={data?.kpis.profit_factor} format="mult" />
              <KpiCard label="Avg Win" kpi={data?.kpis.avg_win} format="inr" />
              <KpiCard label="Avg Loss" kpi={data?.kpis.avg_loss} format="inr" />
              <KpiCard label="Expectancy" kpi={data?.kpis.expectancy} format="inr" />
            </div>
          )}

          {/* 2. Cumulative P&L chart */}
          <Card>
            <CardTitle
              right={
                <div className="flex items-center gap-1">
                  {(["daily", "weekly", "monthly"] as const).map((a) => (
                    <button
                      key={a}
                      onClick={() => setAgg(a)}
                      className={`rounded-md border px-2 py-0.5 text-xs capitalize ${
                        agg === a
                          ? "border-emerald-400 bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
                          : "border-line bg-card text-muted hover:bg-line2"
                      }`}
                    >
                      {a}
                    </button>
                  ))}
                </div>
              }
            >
              Cumulative P&L
            </CardTitle>
            {loading && !data ? (
              <Skeleton className="h-[260px] w-full" />
            ) : (
              <PnLChart days={pnlDays} cumulative={cumulativePoints} height={260} />
            )}
          </Card>

          {/* 3. P&L by Underlying | P&L by Weekday */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <Card>
              <CardTitle>P&L by Underlying</CardTitle>
              {loading && !data ? (
                <Skeleton className="h-[200px] w-full" />
              ) : underlyingItems.length === 0 ? (
                <div className="flex h-[200px] items-center justify-center text-sm text-muted">
                  No trades in this period.
                </div>
              ) : (
                <SimpleDonut items={underlyingItems} />
              )}
            </Card>

            <Card>
              <CardTitle>P&L by Weekday</CardTitle>
              {loading && !data ? (
                <Skeleton className="h-[200px] w-full" />
              ) : (
                <WeekdayBarChart data={data?.pnl_by_weekday ?? []} />
              )}
            </Card>
          </div>

          {/* 4. Top Winners | Top Losers */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <Card>
              <CardTitle>Top Winning Trades</CardTitle>
              {loading && !data ? (
                <Skeleton className="h-[140px] w-full" />
              ) : (
                <TopTradesTable
                  rows={data?.top_winners ?? []}
                  emptyLabel="No trades in this period."
                />
              )}
            </Card>

            <Card>
              <CardTitle>Top Losing Trades</CardTitle>
              {loading && !data ? (
                <Skeleton className="h-[140px] w-full" />
              ) : (
                <TopTradesTable
                  rows={data?.top_losers ?? []}
                  emptyLabel="No losing trades in this period."
                />
              )}
            </Card>
          </div>

          {/* 5. Outcome Distribution | Trade Duration */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <Card>
              <CardTitle>Outcome Distribution</CardTitle>
              {loading && !data ? (
                <Skeleton className="h-[200px] w-full" />
              ) : outcomeItems.length === 0 ? (
                <div className="flex h-[200px] items-center justify-center text-sm text-muted">
                  No trades in this period.
                </div>
              ) : (
                <SimpleDonut items={outcomeItems} />
              )}
            </Card>

            <Card>
              <CardTitle>Trade Duration (Time in Trade)</CardTitle>
              {loading && !data ? (
                <Skeleton className="h-[200px] w-full" />
              ) : data?.trade_duration == null ? (
                <div className="flex h-[200px] items-center justify-center text-center text-sm text-muted px-4">
                  Duration data unavailable (exit timestamps not recorded).
                </div>
              ) : (
                <DurationTable rows={data.trade_duration} />
              )}
            </Card>
          </div>

          {/* 6. Monthly Performance Overview */}
          <Card>
            <CardTitle>Monthly Performance Overview</CardTitle>
            {loading && !data ? (
              <Skeleton className="h-[200px] w-full" />
            ) : (
              <MonthlyTable rows={data?.monthly ?? []} />
            )}
          </Card>
        </div>
      )}

      {/* ---- Condition Analysis tab ---- */}
      {activeTab === "conditions" && (
        <div className="space-y-4">
          {/* 1. Condition Pass Rates */}
          <Card>
            <CardTitle>Condition Pass Rates</CardTitle>
            {loading && !conditionsData ? (
              <Skeleton className="h-[200px] w-full" />
            ) : conditionsData?.pass_rates && conditionsData.pass_rates.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-left text-[10px] uppercase text-muted">
                    <tr className="border-b border-line">
                      <th className="py-2 pr-3">Condition</th>
                      <th className="py-2 pr-3">Label</th>
                      <th className="py-2 pr-3">Status</th>
                      <th className="py-2 pr-3">Scans</th>
                      <th className="py-2 pr-3">Passes</th>
                      <th className="py-2">Pass Rate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {conditionsData.pass_rates.map((r, i) => (
                      <tr key={i} className="border-b border-line2 last:border-0">
                        <td className="py-2 pr-3 font-mono text-ink">{r.condition}</td>
                        <td className="py-2 pr-3 text-ink">{r.label}</td>
                        <td className="py-2 pr-3">
                          <span
                            className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold text-white ${
                              r.status === "active"
                                ? "bg-emerald-600"
                                : r.status === "shadow"
                                ? "bg-amber-600"
                                : "bg-slate-400"
                            }`}
                          >
                            {r.status}
                          </span>
                        </td>
                        <td className="py-2 pr-3 text-ink">{r.scans}</td>
                        <td className="py-2 pr-3 text-ink">{r.passes}</td>
                        <td className="py-2 font-semibold text-emerald-600 dark:text-emerald-400">
                          {r.pass_rate.toFixed(1)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="py-6 text-center text-sm text-muted">No condition data.</div>
            )}
          </Card>

          {/* 2. Signal Funnel */}
          <Card>
            <CardTitle>Signal Funnel</CardTitle>
            {loading && !conditionsData ? (
              <Skeleton className="h-[200px] w-full" />
            ) : conditionsData?.funnel && conditionsData.funnel.length > 0 ? (
              <Histogram
                data={conditionsData.funnel.map((f) => ({
                  bucket: f.bucket,
                  count: f.count,
                }))}
                xLabel="Conditions Passed"
                yLabel="Count"
                height={200}
              />
            ) : (
              <div className="flex h-[200px] items-center justify-center text-sm text-muted">
                No funnel data.
              </div>
            )}
          </Card>

          {/* 3. Blocking Conditions */}
          <Card>
            <CardTitle>Blocking Conditions (Top 5 Near-Misses)</CardTitle>
            {loading && !conditionsData ? (
              <Skeleton className="h-[160px] w-full" />
            ) : conditionsData?.bottleneck && conditionsData.bottleneck.length > 0 ? (
              <div className="space-y-2">
                {conditionsData.bottleneck.map((b, i) => {
                  const maxCount = Math.max(...conditionsData.bottleneck.map((x) => x.blocked_count));
                  const width = maxCount > 0 ? (b.blocked_count / maxCount) * 100 : 0;
                  return (
                    <div key={i} className="flex items-center gap-3">
                      <div className="w-12 font-mono font-semibold text-ink">{b.condition}</div>
                      <div className="flex-1">
                        <div className="h-6 overflow-hidden rounded-md bg-line2">
                          <div
                            className="h-full bg-amber-500 transition-all"
                            style={{ width: `${width}%` }}
                          />
                        </div>
                      </div>
                      <div className="w-16 text-right text-xs font-medium text-ink">
                        {b.blocked_count}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="py-6 text-center text-sm text-muted">No bottleneck data.</div>
            )}
          </Card>

          {/* 4. C5 ADX Shadow Analysis */}
          <Card className="border-amber-300 dark:border-amber-700">
            <CardTitle><span className="text-amber-900 dark:text-amber-200">C5 ADX Shadow Analysis</span></CardTitle>
            {loading && !conditionsData ? (
              <Skeleton className="h-[200px] w-full" />
            ) : conditionsData?.c5_shadow ? (
              <div className="space-y-4">
                <div className="rounded-md bg-amber-50 p-3 dark:bg-amber-950/20">
                  <div className="text-sm font-semibold text-amber-900 dark:text-amber-100">
                    {conditionsData.c5_shadow.c5_pass_rate.toFixed(1)}% of {conditionsData.c5_shadow.alerts_total} alerts
                    had C5 passed
                  </div>
                  <div className="mt-1 text-xs text-amber-700 dark:text-amber-300">
                    Use this data to decide whether to promote C5 from shadow to gating.
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  {/* When C5 Passed */}
                  <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-800 dark:bg-emerald-950/20">
                    <div className="text-[10px] uppercase tracking-wide text-emerald-700 dark:text-emerald-300">
                      When C5 Passed
                    </div>
                    <div className="mt-2 space-y-1">
                      <div className="text-sm font-semibold text-emerald-900 dark:text-emerald-100">
                        n = {conditionsData.c5_shadow.when_c5_passed.n}
                      </div>
                      <div className="text-xs text-emerald-700 dark:text-emerald-300">
                        Win Rate: {conditionsData.c5_shadow.when_c5_passed.win_rate.toFixed(1)}%
                      </div>
                      <div className="text-xs text-emerald-700 dark:text-emerald-300">
                        Avg R: {conditionsData.c5_shadow.when_c5_passed.avg_r.toFixed(2)}R
                      </div>
                    </div>
                  </div>

                  {/* When C5 Failed */}
                  <div className="rounded-md border border-rose-200 bg-rose-50 p-3 dark:border-rose-800 dark:bg-rose-950/20">
                    <div className="text-[10px] uppercase tracking-wide text-rose-700 dark:text-rose-300">
                      When C5 Failed
                    </div>
                    <div className="mt-2 space-y-1">
                      <div className="text-sm font-semibold text-rose-900 dark:text-rose-100">
                        n = {conditionsData.c5_shadow.when_c5_failed.n}
                      </div>
                      <div className="text-xs text-rose-700 dark:text-rose-300">
                        Win Rate: {conditionsData.c5_shadow.when_c5_failed.win_rate.toFixed(1)}%
                      </div>
                      <div className="text-xs text-rose-700 dark:text-rose-300">
                        Avg R: {conditionsData.c5_shadow.when_c5_failed.avg_r.toFixed(2)}R
                      </div>
                    </div>
                  </div>
                </div>

                {conditionsData.c5_shadow.join_note && (
                  <div className="rounded-md bg-slate-100 p-2 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                    {conditionsData.c5_shadow.join_note}
                  </div>
                )}
              </div>
            ) : (
              <div className="py-6 text-center text-sm text-muted">No C5 shadow data.</div>
            )}
          </Card>

          {/* 5. DI Alignment (optional) */}
          {conditionsData?.di_alignment && (
            <Card>
              <CardTitle>DI Alignment (Informational)</CardTitle>
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-md border border-slate-200 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-800">
                  <div className="text-[10px] uppercase tracking-wide text-slate-600 dark:text-slate-400">
                    Spot DI Aligned
                  </div>
                  <div className="mt-2 text-2xl font-semibold text-slate-900 dark:text-slate-100">
                    {conditionsData.di_alignment.spot_aligned_pct.toFixed(1)}%
                  </div>
                </div>
                <div className="rounded-md border border-slate-200 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-800">
                  <div className="text-[10px] uppercase tracking-wide text-slate-600 dark:text-slate-400">
                    Option DI Aligned
                  </div>
                  <div className="mt-2 text-2xl font-semibold text-slate-900 dark:text-slate-100">
                    {conditionsData.di_alignment.option_aligned_pct.toFixed(1)}%
                  </div>
                </div>
              </div>
              <p className="mt-3 text-xs text-muted">{conditionsData.di_alignment.note}</p>
            </Card>
          )}
        </div>
      )}

      {/* ---- Risk Analysis tab ---- */}
      {activeTab === "risk" && (
        <div className="space-y-4">
          {/* 1. R-Multiple Distribution */}
          <Card>
            <CardTitle>R-Multiple Distribution (TAKEN Trades)</CardTitle>
            {loading && !riskData ? (
              <Skeleton className="h-[200px] w-full" />
            ) : riskData?.r_distribution && riskData.r_distribution.length > 0 ? (
              <Histogram
                data={riskData.r_distribution}
                xLabel="R Multiple"
                yLabel="Count"
                height={200}
              />
            ) : (
              <div className="flex h-[200px] items-center justify-center text-sm text-muted">
                No R-distribution data.
              </div>
            )}
          </Card>

          {/* 2. Equity Curve & Drawdown */}
          <Card>
            <CardTitle>Equity Curve & Drawdown</CardTitle>
            {loading && !riskData ? (
              <Skeleton className="h-[300px] w-full" />
            ) : riskData?.equity_curve && riskData.equity_curve.length > 0 ? (
              <div>
                <PnLChart
                  days={riskData.equity_curve.map((p) => ({
                    date: p.date,
                    realized_pnl: p.equity,
                    is_profit: p.equity >= 0,
                  }))}
                  cumulative={riskData.equity_curve.map((p) => ({
                    date: p.date,
                    net: p.equity,
                  }))}
                  height={240}
                />
                <div className="mt-3 grid grid-cols-2 gap-2">
                  <div className="rounded-md bg-slate-50 p-2 dark:bg-slate-800">
                    <div className="text-[10px] uppercase text-muted">Max Drawdown (₹)</div>
                    <div className="text-lg font-semibold text-rose-600 dark:text-rose-400">
                      {riskData.max_drawdown.rupees.toLocaleString("en-IN", {
                        style: "currency",
                        currency: "INR",
                        minimumFractionDigits: 0,
                      })}
                    </div>
                  </div>
                  <div className="rounded-md bg-slate-50 p-2 dark:bg-slate-800">
                    <div className="text-[10px] uppercase text-muted">Max Drawdown (R)</div>
                    <div className="text-lg font-semibold text-rose-600 dark:text-rose-400">
                      {riskData.max_drawdown.r.toFixed(2)}R
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex h-[300px] items-center justify-center text-sm text-muted">
                No equity curve data.
              </div>
            )}
          </Card>

          {/* 3. Streaks */}
          <Card>
            <CardTitle>Current Streaks</CardTitle>
            {loading && !riskData ? (
              <Skeleton className="h-[120px] w-full" />
            ) : riskData?.streaks ? (
              <div className="grid grid-cols-3 gap-3">
                <div className="rounded-md border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-800">
                  <div className="text-[10px] uppercase tracking-wide text-muted">Current</div>
                  <div className="mt-2 text-2xl font-semibold text-ink">
                    {riskData.streaks.current === 0
                      ? "—"
                      : riskData.streaks.current > 0
                      ? `W${riskData.streaks.current}`
                      : `L${Math.abs(riskData.streaks.current)}`}
                  </div>
                </div>
                <div className="rounded-md border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-800 dark:bg-emerald-950/20">
                  <div className="text-[10px] uppercase tracking-wide text-emerald-700 dark:text-emerald-300">
                    Max Win
                  </div>
                  <div className="mt-2 text-2xl font-semibold text-emerald-700 dark:text-emerald-300">
                    {riskData.streaks.max_win > 0 ? `W${riskData.streaks.max_win}` : "—"}
                  </div>
                </div>
                <div className="rounded-md border border-rose-200 bg-rose-50 p-4 dark:border-rose-800 dark:bg-rose-950/20">
                  <div className="text-[10px] uppercase tracking-wide text-rose-700 dark:text-rose-300">
                    Max Loss
                  </div>
                  <div className="mt-2 text-2xl font-semibold text-rose-700 dark:text-rose-300">
                    {riskData.streaks.max_loss > 0 ? `L${riskData.streaks.max_loss}` : "—"}
                  </div>
                </div>
              </div>
            ) : (
              <div className="py-6 text-center text-sm text-muted">No streak data.</div>
            )}
          </Card>

          {/* 4. Payoff Metrics */}
          <Card>
            <CardTitle>Payoff Metrics</CardTitle>
            {loading && !riskData ? (
              <Skeleton className="h-[120px] w-full" />
            ) : riskData?.payoff ? (
              <div className="grid grid-cols-3 gap-3">
                <div className="rounded-md border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-800 dark:bg-emerald-950/20">
                  <div className="text-[10px] uppercase tracking-wide text-emerald-700 dark:text-emerald-300">
                    Avg Win
                  </div>
                  <div className="mt-2 text-2xl font-semibold text-emerald-700 dark:text-emerald-300">
                    {riskData.payoff.avg_win_r.toFixed(2)}R
                  </div>
                </div>
                <div className="rounded-md border border-rose-200 bg-rose-50 p-4 dark:border-rose-800 dark:bg-rose-950/20">
                  <div className="text-[10px] uppercase tracking-wide text-rose-700 dark:text-rose-300">
                    Avg Loss
                  </div>
                  <div className="mt-2 text-2xl font-semibold text-rose-700 dark:text-rose-300">
                    {riskData.payoff.avg_loss_r.toFixed(2)}R
                  </div>
                </div>
                <div className="rounded-md border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-800">
                  <div className="text-[10px] uppercase tracking-wide text-muted">Payoff Ratio</div>
                  <div className="mt-2 text-2xl font-semibold text-ink">
                    {riskData.payoff.ratio != null ? `${riskData.payoff.ratio.toFixed(2)}×` : "—"}
                  </div>
                </div>
              </div>
            ) : (
              <div className="py-6 text-center text-sm text-muted">No payoff data.</div>
            )}
          </Card>

          {/* 5. MFE / MAE (optional) */}
          {riskData?.mfe_mae && (
            <Card>
              <CardTitle>MFE / MAE (Max Favorable / Adverse Excursion in R)</CardTitle>
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-800 dark:bg-emerald-950/20">
                  <div className="text-[10px] uppercase tracking-wide text-emerald-700 dark:text-emerald-300">
                    Avg Favorable Excursion
                  </div>
                  <div className="mt-2 text-lg font-semibold text-emerald-700 dark:text-emerald-300">
                    {riskData.mfe_mae.avg_mfe_r.toFixed(2)}R
                  </div>
                </div>
                <div className="rounded-md border border-rose-200 bg-rose-50 p-3 dark:border-rose-800 dark:bg-rose-950/20">
                  <div className="text-[10px] uppercase tracking-wide text-rose-700 dark:text-rose-300">
                    Avg Adverse Excursion
                  </div>
                  <div className="mt-2 text-lg font-semibold text-rose-700 dark:text-rose-300">
                    {riskData.mfe_mae.avg_mae_r.toFixed(2)}R
                  </div>
                </div>
              </div>
            </Card>
          )}

          {/* 6. Risk Adherence */}
          <Card>
            <CardTitle>Risk Adherence vs Config</CardTitle>
            {loading && !riskData ? (
              <Skeleton className="h-[260px] w-full" />
            ) : riskData?.risk_adherence ? (
              <div className="space-y-3">
                <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-800">
                  <div className="grid grid-cols-3 gap-2 text-xs">
                    <div>
                      <div className="text-muted">Target</div>
                      <div className="font-semibold text-ink">
                        ₹{riskData.risk_adherence.target.toLocaleString("en-IN")}
                      </div>
                    </div>
                    <div>
                      <div className="text-muted">Range</div>
                      <div className="font-semibold text-ink">
                        ₹{riskData.risk_adherence.range_min.toLocaleString("en-IN")}–₹
                        {riskData.risk_adherence.range_max.toLocaleString("en-IN")}
                      </div>
                    </div>
                    <div>
                      <div className="text-muted">Within Range</div>
                      <div className="font-semibold text-emerald-600 dark:text-emerald-400">
                        {riskData.risk_adherence.within_range_pct.toFixed(1)}%
                      </div>
                    </div>
                  </div>
                </div>
                {riskData.risk_adherence.distribution.length > 0 && (
                  <Histogram
                    data={riskData.risk_adherence.distribution}
                    xLabel="Risk Amount"
                    yLabel="Count"
                    height={180}
                  />
                )}
              </div>
            ) : (
              <div className="py-6 text-center text-sm text-muted">No risk adherence data.</div>
            )}
          </Card>
        </div>
      )}

      {activeTab !== "performance" && activeTab !== "conditions" && activeTab !== "risk" && (
        <ComingSoonTab label={TABS.find((t) => t.id === activeTab)?.label ?? ""} />
      )}

      {/* Footer */}
      <div className="pb-4 pt-2 text-center text-xs text-muted">
        All times are IST (Asia/Kolkata). Paper P&L; outcomes finalize at EOD.
      </div>
    </div>
  );
}
