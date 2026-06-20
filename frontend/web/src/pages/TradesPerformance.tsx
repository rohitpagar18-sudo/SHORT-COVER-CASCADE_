import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ChevronDown, ChevronRight, RefreshCw, Filter, BarChart3,
  TrendingUp, TrendingDown, Wallet, ListChecks, CheckCircle2, XCircle, Award,
} from "lucide-react";
import { Card, CardTitle, StatTile, Skeleton } from "../components/Card";
import OpenPositionTracker from "../components/positions/OpenPositionTracker";
import PnLChart from "../components/charts/PnLChart";
import StatPanel from "../components/charts/StatPanel";
import {
  api,
  type TradesResponse,
  type TradesHistoryResponse,
  type TradeRow,
  type TradeFilters,
  type HistoryGroup,
} from "../lib/api";
import { inr, inrSigned, hhmm } from "../lib/format";

const POLL_MS = 15_000;

type GroupBy = "day" | "week" | "month";
type ChartUnit = "inr" | "pct";
type SymbolFilter = "ALL" | "NIFTY" | "BANKNIFTY";
type TypeFilter = "ALL" | "CE" | "PE";
type StatusFilter = "ALL" | "TAKEN" | "SKIPPED";
type OutcomeFilter =
  | "ALL"
  | "TP2_HIT"
  | "TP1_HIT"
  | "SL_HIT"
  | "NO_DATA"
  | "PARTIAL"
  | "WOULD_SKIP";

type Preset = "today" | "this_week" | "this_month" | "last_week" | "last_month" | "custom";

function todayIST(): Date {
  const now = new Date();
  return new Date(now.getTime() + (now.getTimezoneOffset() + 330) * 60_000);
}

function toISO(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function startOfWeekMon(d: Date): Date {
  const out = new Date(d);
  const day = (out.getUTCDay() + 6) % 7; // Mon=0
  out.setUTCDate(out.getUTCDate() - day);
  return out;
}

function endOfWeekSun(d: Date): Date {
  const s = startOfWeekMon(d);
  s.setUTCDate(s.getUTCDate() + 6);
  return s;
}

function startOfMonth(d: Date): Date {
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1));
}

function endOfMonth(d: Date): Date {
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0));
}

function applyPreset(preset: Preset): { from: string; to: string } {
  const t = todayIST();
  if (preset === "today") {
    return { from: toISO(t), to: toISO(t) };
  }
  if (preset === "this_week") {
    return { from: toISO(startOfWeekMon(t)), to: toISO(endOfWeekSun(t)) };
  }
  if (preset === "last_week") {
    const lastWeekRef = new Date(t);
    lastWeekRef.setUTCDate(lastWeekRef.getUTCDate() - 7);
    return { from: toISO(startOfWeekMon(lastWeekRef)), to: toISO(endOfWeekSun(lastWeekRef)) };
  }
  if (preset === "this_month") {
    return { from: toISO(startOfMonth(t)), to: toISO(endOfMonth(t)) };
  }
  if (preset === "last_month") {
    const ref = startOfMonth(t);
    ref.setUTCMonth(ref.getUTCMonth() - 1);
    return { from: toISO(startOfMonth(ref)), to: toISO(endOfMonth(ref)) };
  }
  return { from: toISO(t), to: toISO(t) };
}

function presetLabel(p: Preset): string {
  return {
    today: "Today",
    this_week: "This Week",
    this_month: "This Month",
    last_week: "Last Week",
    last_month: "Last Month",
    custom: "Custom",
  }[p];
}

export default function TradesPerformancePage() {
  const initial = applyPreset("this_week");
  const [preset, setPreset] = useState<Preset>("this_week");
  const [from, setFrom] = useState<string>(initial.from);
  const [to, setTo] = useState<string>(initial.to);
  const [symbol, setSymbol] = useState<SymbolFilter>("ALL");
  const [optType, setOptType] = useState<TypeFilter>("ALL");
  const [status, setStatus] = useState<StatusFilter>("ALL");
  const [outcome, setOutcome] = useState<OutcomeFilter>("ALL");

  // Applied filters (only update when user clicks "Apply").
  const [applied, setApplied] = useState({
    from: initial.from,
    to: initial.to,
    symbol: "ALL" as SymbolFilter,
    optType: "ALL" as TypeFilter,
    status: "ALL" as StatusFilter,
    outcome: "ALL" as OutcomeFilter,
    // Immediately apply the initial preset — no need to click Apply.
  });

  const [trades, setTrades] = useState<TradesResponse | null>(null);
  const [tradesErr, setTradesErr] = useState<string | null>(null);
  const [history, setHistory] = useState<TradesHistoryResponse | null>(null);
  const [historyErr, setHistoryErr] = useState<string | null>(null);
  const [groupBy, setGroupBy] = useState<GroupBy>("day");
  const [chartUnit, setChartUnit] = useState<ChartUnit>("inr");

  const tradeFilters: Partial<TradeFilters> = useMemo(() => ({
    date_from: applied.from || undefined,
    date_to: applied.to || undefined,
    symbol: applied.symbol === "ALL" ? undefined : applied.symbol,
    option_type: applied.optType === "ALL" ? undefined : applied.optType,
    status: applied.status === "ALL" ? undefined : applied.status,
    outcome: applied.outcome === "ALL" ? undefined : applied.outcome,
  }), [applied]);

  // Trades + KPIs: poll every 15s.
  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const d = await api.trades(tradeFilters);
        if (!alive) return;
        setTrades(d);
        setTradesErr(null);
      } catch (e: unknown) {
        if (!alive) return;
        setTradesErr((e as Error)?.message ?? "failed to load");
      } finally {
        if (alive) timer = window.setTimeout(tick, POLL_MS);
      }
    };
    tick();
    return () => {
      alive = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [tradeFilters]);

  // History: refetch on filter / group_by change (no polling).
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const d = await api.tradesHistory({ ...tradeFilters, group_by: groupBy });
        if (!alive) return;
        setHistory(d);
        setHistoryErr(null);
      } catch (e: unknown) {
        if (!alive) return;
        setHistoryErr((e as Error)?.message ?? "failed to load");
      }
    })();
    return () => {
      alive = false;
    };
  }, [tradeFilters, groupBy]);

  const onPickPreset = useCallback((p: Preset) => {
    setPreset(p);
    if (p !== "custom") {
      const r = applyPreset(p);
      setFrom(r.from);
      setTo(r.to);
    }
  }, []);

  const onApply = useCallback(() => {
    setApplied({
      from,
      to,
      symbol,
      optType,
      status,
      outcome,
    });
  }, [from, to, symbol, optType, status, outcome]);

  const onReset = useCallback(() => {
    const r = applyPreset("this_week");
    setPreset("this_week");
    setFrom(r.from);
    setTo(r.to);
    setSymbol("ALL");
    setOptType("ALL");
    setStatus("ALL");
    setOutcome("ALL");
    setApplied({ from: r.from, to: r.to, symbol: "ALL", optType: "ALL", status: "ALL", outcome: "ALL" });
  }, []);

  return (
    <div className="space-y-4">
      <OpenPositionTracker />

      <KpiRow trades={trades} err={tradesErr} />

      <FilterBar
        preset={preset}
        from={from}
        to={to}
        symbol={symbol}
        optType={optType}
        status={status}
        outcome={outcome}
        onPickPreset={onPickPreset}
        onFromChange={(v) => { setFrom(v); setPreset("custom"); }}
        onToChange={(v) => { setTo(v); setPreset("custom"); }}
        onSymbol={setSymbol}
        onOptType={setOptType}
        onStatus={setStatus}
        onOutcome={setOutcome}
        onApply={onApply}
        onReset={onReset}
      />

      <TodaysTradesTable trades={trades} err={tradesErr} appliedFrom={applied.from} appliedTo={applied.to} />

      <DailyPnLPanel trades={trades} chartUnit={chartUnit} onUnitChange={setChartUnit} />

      <HistoryPanel
        history={history}
        err={historyErr}
        groupBy={groupBy}
        onGroupByChange={setGroupBy}
      />

      <div className="pt-2 text-center text-xs text-muted">
        All times are IST (Asia/Kolkata). Paper P&L; updates each 5-min scan,
        outcomes finalized at EOD.
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// KPI row
// ---------------------------------------------------------------------------

function KpiRow({ trades, err }: { trades: TradesResponse | null; err: string | null }) {
  if (!trades && err) {
    return (
      <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700 dark:bg-rose-950/40 dark:text-rose-200">
        Failed to load trades: {err}
      </div>
    );
  }
  if (!trades) {
    return (
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 2xl:grid-cols-8">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="rounded-xl border border-line bg-card p-4">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="mt-3 h-6 w-28" />
            <Skeleton className="mt-2 h-3 w-16" />
          </div>
        ))}
      </div>
    );
  }
  const k = trades.kpis;
  const totalTone = k.total_pnl >= 0 ? "ok" : "bad";
  const realizedTone = k.realized_pnl >= 0 ? "ok" : "bad";
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4 2xl:grid-cols-8">
      <StatTile icon={<ListChecks className="h-4 w-4" />} label="Total Trades" value={k.total_trades} sub="finalized" />
      <StatTile
        icon={<CheckCircle2 className="h-4 w-4" />}
        label="Winning"
        value={k.winning_trades}
        tone="ok"
        sub={`${k.winning_pct.toFixed(1)}%`}
      />
      <StatTile
        icon={<XCircle className="h-4 w-4" />}
        label="Losing"
        value={k.losing_trades}
        tone="bad"
        sub={`${k.losing_pct.toFixed(1)}%`}
      />
      <StatTile
        icon={<Wallet className="h-4 w-4" />}
        label="Total P&L"
        value={inrSigned(k.total_pnl)}
        tone={totalTone as "ok" | "bad"}
        sub="realized + unrealized"
      />
      <StatTile
        icon={<TrendingUp className="h-4 w-4" />}
        label="Realized"
        value={inrSigned(k.realized_pnl)}
        tone={realizedTone as "ok" | "bad"}
        sub="finalized trades"
      />
      <StatTile
        icon={<BarChart3 className="h-4 w-4" />}
        label="Unrealized"
        value={inrSigned(k.unrealized_pnl)}
        tone="neutral"
        sub="open positions"
      />
      <StatTile
        icon={<Award className="h-4 w-4" />}
        label="Max Daily Profit"
        value={inr(k.max_daily_profit)}
        tone="ok"
      />
      <StatTile
        icon={<TrendingDown className="h-4 w-4" />}
        label="Max Daily Loss"
        value={inr(k.max_daily_loss)}
        tone="bad"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Filter bar
// ---------------------------------------------------------------------------

const PRESETS: Preset[] = ["today", "this_week", "this_month", "last_week", "last_month", "custom"];

function FilterBar(props: {
  preset: Preset;
  from: string;
  to: string;
  symbol: SymbolFilter;
  optType: TypeFilter;
  status: StatusFilter;
  outcome: OutcomeFilter;
  onPickPreset: (p: Preset) => void;
  onFromChange: (v: string) => void;
  onToChange: (v: string) => void;
  onSymbol: (v: SymbolFilter) => void;
  onOptType: (v: TypeFilter) => void;
  onStatus: (v: StatusFilter) => void;
  onOutcome: (v: OutcomeFilter) => void;
  onApply: () => void;
  onReset: () => void;
}) {
  return (
    <Card>
      <CardTitle>
        <span className="flex items-center gap-2">
          <Filter className="h-4 w-4" /> Filters
        </span>
      </CardTitle>
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <Label>Date range</Label>
          <div className="flex flex-wrap gap-1">
            {PRESETS.map((p) => (
              <button
                key={p}
                onClick={() => props.onPickPreset(p)}
                className={
                  "rounded-md border px-2 py-1 text-xs " +
                  (props.preset === p
                    ? "border-emerald-400 bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
                    : "border-line bg-card text-ink hover:bg-line2")
                }
              >
                {presetLabel(p)}
              </button>
            ))}
          </div>
        </div>
        <div>
          <Label>From</Label>
          <input
            type="date"
            value={props.from}
            onChange={(e) => props.onFromChange(e.target.value)}
            className="rounded-md border border-line bg-card px-2 py-1 text-sm text-ink"
          />
        </div>
        <div>
          <Label>To</Label>
          <input
            type="date"
            value={props.to}
            onChange={(e) => props.onToChange(e.target.value)}
            className="rounded-md border border-line bg-card px-2 py-1 text-sm text-ink"
          />
        </div>
        <SelectBlock label="Symbol" value={props.symbol} onChange={(v) => props.onSymbol(v as SymbolFilter)}
          options={["ALL", "NIFTY", "BANKNIFTY"]} />
        <SelectBlock label="Type" value={props.optType} onChange={(v) => props.onOptType(v as TypeFilter)}
          options={["ALL", "CE", "PE"]} />
        <SelectBlock label="Status" value={props.status} onChange={(v) => props.onStatus(v as StatusFilter)}
          options={["ALL", "TAKEN", "SKIPPED"]} />
        <SelectBlock label="Outcome" value={props.outcome} onChange={(v) => props.onOutcome(v as OutcomeFilter)}
          options={["ALL", "TP2_HIT", "TP1_HIT", "SL_HIT", "NO_DATA", "PARTIAL", "WOULD_SKIP"]} />
        <div className="flex gap-2">
          <button
            onClick={props.onApply}
            className="rounded-md border border-emerald-500 bg-emerald-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-600"
          >
            Apply
          </button>
          <button
            onClick={props.onReset}
            className="flex items-center gap-1.5 rounded-md border border-line bg-card px-3 py-1.5 text-sm text-ink hover:bg-line2"
          >
            <RefreshCw className="h-3.5 w-3.5" /> Reset
          </button>
        </div>
      </div>
    </Card>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return <div className="mb-1 text-[10px] uppercase tracking-wide text-muted">{children}</div>;
}

function SelectBlock({
  label, value, onChange, options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <div>
      <Label>{label}</Label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-line bg-card px-2 py-1 text-sm text-ink"
      >
        {options.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Today's trades table
// ---------------------------------------------------------------------------

function TodaysTradesTable({
  trades, err, appliedFrom, appliedTo,
}: {
  trades: TradesResponse | null;
  err: string | null;
  appliedFrom: string;
  appliedTo: string;
}) {
  const isToday = appliedFrom === appliedTo && appliedFrom === toISO(todayIST());
  return (
    <Card>
      <CardTitle
        right={
          <span className="text-xs text-muted">
            {isToday ? "Today" : `${appliedFrom} → ${appliedTo}`} ·{" "}
            {trades?.trades.length ?? 0} row{trades && trades.trades.length === 1 ? "" : "s"}
          </span>
        }
      >
        {isToday ? "Today's Trades" : "Trades"}
      </CardTitle>
      {!trades && err ? (
        <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700 dark:bg-rose-950/40 dark:text-rose-200">
          Failed to load: {err}
        </div>
      ) : !trades ? (
        <Skeleton className="h-24 w-full" />
      ) : trades.trades.length === 0 ? (
        <div className="py-6 text-center text-sm text-muted">No trades in this range.</div>
      ) : (
        <>
          <TradesTable rows={trades.trades} />
          <TotalsRow rows={trades.trades} />
        </>
      )}
      <OutcomeLegend />
    </Card>
  );
}

function TradesTable({ rows }: { rows: TradeRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs uppercase text-muted">
          <tr className="border-b border-line">
            <th className="py-2 pr-3">Time</th>
            <th className="py-2 pr-3">Symbol</th>
            <th className="py-2 pr-3">Type</th>
            <th className="py-2 pr-3">Strike</th>
            <th className="py-2 pr-3">Qty (Lots)</th>
            <th className="py-2 pr-3">Buy</th>
            <th className="py-2 pr-3">Sell</th>
            <th className="py-2 pr-3">SL</th>
            <th className="py-2 pr-3">TP1</th>
            <th className="py-2 pr-3">TP2</th>
            <th className="py-2 pr-3">P&L</th>
            <th className="py-2 pr-3">Status</th>
            <th className="py-2 pr-3">Outcome</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => {
            const pnl = t.pnl ?? 0;
            const pnlClass =
              t.pnl == null ? "text-muted" : pnl > 0 ? "text-emerald-600" : pnl < 0 ? "text-rose-600" : "text-ink";
            return (
              <tr key={`${t.alert_id}-${t.candle_timestamp}`} className="border-b border-line2 last:border-0">
                <td className="py-2 pr-3 font-mono text-xs">{t.time || hhmm(t.candle_timestamp)}</td>
                <td className="py-2 pr-3">{t.symbol ?? "—"}</td>
                <td className="py-2 pr-3">{t.option_type ?? "—"}</td>
                <td className="py-2 pr-3">
                  {t.strike ?? "—"}
                  {t.relation && (
                    <span className="ml-1 text-[10px] text-muted">({t.relation})</span>
                  )}
                </td>
                <td className="py-2 pr-3">{t.qty_lots ?? "—"}</td>
                <td className="py-2 pr-3">{t.buy_price != null ? inr(t.buy_price) : "—"}</td>
                <td className="py-2 pr-3">
                  <SellCell row={t} />
                </td>
                <td className="py-2 pr-3">{t.sl != null ? inr(t.sl) : "—"}</td>
                <td className="py-2 pr-3">{t.tp1 != null ? inr(t.tp1) : "—"}</td>
                <td className="py-2 pr-3">{t.tp2 != null ? inr(t.tp2) : "—"}</td>
                <td className={`py-2 pr-3 font-semibold ${pnlClass}`}>
                  {t.pnl == null ? "—" : inrSigned(t.pnl)}
                </td>
                <td className="py-2 pr-3">
                  <StatusBadge value={t.status} />
                </td>
                <td className="py-2 pr-3">
                  <OutcomeBadge value={t.outcome} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function TotalsRow({ rows }: { rows: TradeRow[] }) {
  const total = rows.reduce((acc, r) => acc + (typeof r.pnl === "number" ? r.pnl : 0), 0);
  const wins = rows.filter((r) => (r.outcome === "TP2_HIT" || r.outcome === "TP1_HIT") && (r.pnl ?? 0) > 0).length;
  const losses = rows.filter((r) => r.outcome === "SL_HIT").length;
  return (
    <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-md border border-line2 bg-bg px-3 py-2 text-xs">
      <span className="text-muted">
        <span className="font-medium text-ink">{rows.length}</span> rows · {wins} win
        {wins === 1 ? "" : "s"} · {losses} loss{losses === 1 ? "" : "es"}
      </span>
      <span>
        <span className="text-muted">Total P&L: </span>
        <span className={total >= 0 ? "font-semibold text-emerald-600" : "font-semibold text-rose-600"}>
          {inrSigned(total)}
        </span>
      </span>
    </div>
  );
}

function SellCell({ row }: { row: TradeRow }) {
  const leg1 = row.sell_price_leg1;
  const leg2 = row.sell_price_leg2;
  if (leg1 != null && leg2 != null) {
    const avg = 0.5 * leg1 + 0.5 * leg2;
    const tip =
      `Leg 1 (TP1): ${inr(leg1)} | ` +
      `Leg 2 (${row.outcome === "TP1_HIT" ? "EOD" : "Trail SL"}): ${inr(leg2)} | ` +
      `Avg: ${inr(avg)}`;
    return (
      <span title={tip} className="whitespace-nowrap">
        {inr(leg1)} <span className="text-muted">→</span> {inr(leg2)}
      </span>
    );
  }
  return <>{row.sell_price != null ? inr(row.sell_price) : "—"}</>;
}

function StatusBadge({ value }: { value: string | null }) {
  const tone =
    value === "TAKEN" ? "ok" : value === "SKIPPED" ? "neutral" : "neutral";
  return <Badge tone={tone as "ok" | "neutral"}>{value ?? "—"}</Badge>;
}

function OutcomeBadge({ value }: { value: string | null }) {
  if (value == null) return <Badge tone="neutral">—</Badge>;
  const tone = (() => {
    if (value === "TP2_HIT") return "ok";
    if (value === "TP1_HIT") return "ok-light";
    if (value === "SL_HIT") return "bad";
    if (value === "NO_DATA") return "running";
    if (value === "PARTIAL") return "warn";
    if (value === "WOULD_SKIP") return "neutral";
    return "neutral";
  })();
  const label =
    value === "NO_DATA" ? "RUN" :
    value === "TP2_HIT" ? "TP2 HIT" :
    value === "TP1_HIT" ? "TP1 HIT" :
    value === "SL_HIT" ? "SL HIT" :
    value === "WOULD_SKIP" ? "SKIPPED" :
    value;
  return <Badge tone={tone}>{label}</Badge>;
}

function Badge({
  tone,
  children,
}: {
  tone: "ok" | "ok-light" | "bad" | "warn" | "neutral" | "running";
  children: React.ReactNode;
}) {
  const cls = {
    ok: "bg-emerald-100 text-emerald-700 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:ring-emerald-900",
    "ok-light": "bg-emerald-50 text-emerald-600 ring-emerald-100 dark:bg-emerald-950/30 dark:text-emerald-300 dark:ring-emerald-900",
    bad: "bg-rose-100 text-rose-700 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-300 dark:ring-rose-900",
    warn: "bg-amber-100 text-amber-700 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:ring-amber-900",
    neutral: "bg-slate-100 text-slate-700 ring-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:ring-slate-700",
    running: "bg-sky-100 text-sky-700 ring-sky-200 dark:bg-sky-950/40 dark:text-sky-300 dark:ring-sky-900",
  }[tone];
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1 ${cls}`}>
      {children}
    </span>
  );
}

function OutcomeLegend() {
  const items: Array<{ label: string; tone: "ok" | "ok-light" | "bad" | "warn" | "neutral" | "running" }> = [
    { label: "TP2 HIT", tone: "ok" },
    { label: "TP1 HIT", tone: "ok-light" },
    { label: "SL HIT", tone: "bad" },
    { label: "PARTIAL", tone: "warn" },
    { label: "RUN", tone: "running" },
    { label: "SKIPPED", tone: "neutral" },
  ];
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-muted">
      <span>Legend:</span>
      {items.map((it) => (
        <Badge key={it.label} tone={it.tone}>{it.label}</Badge>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Daily P&L panel
// ---------------------------------------------------------------------------

function DailyPnLPanel({
  trades, chartUnit, onUnitChange,
}: {
  trades: TradesResponse | null;
  chartUnit: ChartUnit;
  onUnitChange: (u: ChartUnit) => void;
}) {
  const days = useMemo(() => trades?.daily_series ?? [], [trades]);
  // The Overview ComposedChart wants PnlDay[] + CumulativePoint[]. Map.
  const pnlDays = days.map((d) => ({
    date: d.date, realized_pnl: d.realized_pnl, is_profit: d.is_profit,
  }));
  const cumulative = days.map((d) => ({ date: d.date, net: d.net }));
  return (
    <Card>
      <CardTitle
        right={
          <div className="flex items-center gap-2">
            <button
              onClick={() => onUnitChange("inr")}
              className={`rounded-md border px-2 py-0.5 text-xs ${chartUnit === "inr" ? "border-emerald-400 bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300" : "border-line bg-card text-muted hover:bg-line2"}`}
            >₹</button>
            <button
              onClick={() => onUnitChange("pct")}
              className={`rounded-md border px-2 py-0.5 text-xs ${chartUnit === "pct" ? "border-emerald-400 bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300" : "border-line bg-card text-muted hover:bg-line2"}`}
            >%</button>
          </div>
        }
      >
        Daily P&L Overview (Paper)
      </CardTitle>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_180px]">
        <div>
          {chartUnit === "pct" ? (
            <PercentChart days={days} />
          ) : (
            <PnLChart days={pnlDays} cumulative={cumulative} height={260} />
          )}
        </div>
        {trades && (
          <StatPanel totals={{
            total_pnl: trades.kpis.total_pnl,
            realized_pnl: trades.kpis.realized_pnl,
            unrealized_pnl: trades.kpis.unrealized_pnl,
            max_daily_profit: trades.kpis.max_daily_profit,
            max_daily_loss: trades.kpis.max_daily_loss,
          }} />
        )}
      </div>
    </Card>
  );
}

/** Lightweight % view: each bar = day P&L / target_risk_per_trade.
 * We don't have config here, so we use the max absolute P&L as 100%
 * to keep it self-contained and honest about being a relative view. */
function PercentChart({ days }: { days: Array<{ date: string; realized_pnl: number; net: number }> }) {
  const maxAbs = Math.max(1, ...days.map((d) => Math.abs(d.realized_pnl)));
  if (days.length === 0) {
    return (
      <div className="flex h-[200px] items-center justify-center text-sm text-muted">
        No P&L data in this window.
      </div>
    );
  }
  return (
    <div className="space-y-1.5">
      {days.map((d) => {
        const pct = (d.realized_pnl / maxAbs) * 100;
        const pos = pct >= 0;
        return (
          <div key={d.date} className="flex items-center gap-3 text-xs">
            <span className="w-20 font-mono text-muted">{d.date.slice(5)}</span>
            <div className="relative h-3 flex-1 rounded bg-line2">
              <div
                className={`absolute top-0 h-full rounded ${pos ? "left-1/2 bg-emerald-500" : "right-1/2 bg-rose-500"}`}
                style={{ width: `${Math.abs(pct) / 2}%` }}
              />
              <div className="absolute left-1/2 top-0 h-full w-px bg-muted" />
            </div>
            <span className={`w-24 text-right font-semibold ${pos ? "text-emerald-600" : "text-rose-600"}`}>
              {pct.toFixed(1)}%
            </span>
          </div>
        );
      })}
      <div className="pt-1 text-[10px] text-muted">
        Bars normalized to the largest absolute daily P&L (₹{maxAbs.toFixed(0)}) in the window.
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// History panel — Group by Day / Week / Month, expandable rows
// ---------------------------------------------------------------------------

function HistoryPanel({
  history, err, groupBy, onGroupByChange,
}: {
  history: TradesHistoryResponse | null;
  err: string | null;
  groupBy: GroupBy;
  onGroupByChange: (g: GroupBy) => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <Card>
      <CardTitle
        right={
          <div className="flex items-center gap-1">
            {(["day", "week", "month"] as GroupBy[]).map((g) => (
              <button
                key={g}
                onClick={() => onGroupByChange(g)}
                className={`rounded-md border px-2 py-0.5 text-xs capitalize ${groupBy === g ? "border-emerald-400 bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300" : "border-line bg-card text-muted hover:bg-line2"}`}
              >
                {g}
              </button>
            ))}
          </div>
        }
      >
        Trade History
      </CardTitle>
      {!history && err ? (
        <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700 dark:bg-rose-950/40 dark:text-rose-200">
          Failed to load history: {err}
        </div>
      ) : !history ? (
        <Skeleton className="h-24 w-full" />
      ) : history.groups.length === 0 ? (
        <div className="py-6 text-center text-sm text-muted">No trades in this range.</div>
      ) : (
        <ul className="divide-y divide-line2">
          {history.groups.map((g) => (
            <HistoryRow
              key={g.period_start}
              group={g}
              open={expanded.has(g.period_start)}
              onToggle={() => toggle(g.period_start)}
            />
          ))}
        </ul>
      )}
    </Card>
  );
}

function HistoryRow({
  group, open, onToggle,
}: {
  group: HistoryGroup;
  open: boolean;
  onToggle: () => void;
}) {
  const totalTone = group.total_pnl >= 0 ? "text-emerald-600" : "text-rose-600";
  return (
    <li>
      <button
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-3 py-2 text-left"
      >
        <span className="flex items-center gap-2">
          {open ? <ChevronDown className="h-4 w-4 text-muted" /> : <ChevronRight className="h-4 w-4 text-muted" />}
          <span className="font-medium text-ink">{group.period_label}</span>
          <span className="text-xs text-muted">
            ({group.total_trades} trade{group.total_trades === 1 ? "" : "s"} · {group.win_rate.toFixed(1)}% win)
          </span>
        </span>
        <span className={`text-sm font-semibold ${totalTone}`}>{inrSigned(group.total_pnl)}</span>
      </button>
      {open && (
        <div className="space-y-3 pb-3 pl-6 pr-1">
          <div className="grid grid-cols-2 gap-2 text-xs md:grid-cols-6">
            <Stat label="Total Trades" value={group.total_trades} />
            <Stat label="Win Rate" value={`${group.win_rate.toFixed(1)}%`} />
            <Stat label="Total P&L" value={inrSigned(group.total_pnl)} tone={group.total_pnl >= 0 ? "ok" : "bad"} />
            <Stat label="Realized" value={inrSigned(group.realized_pnl)} />
            <Stat label="Unrealized" value={inrSigned(group.unrealized_pnl)} />
            <Stat label="Max Day Profit" value={inr(group.max_profit)} tone="ok" />
          </div>
          {group.trades.length === 0 ? (
            <div className="text-xs text-muted">No trades recorded in this period.</div>
          ) : (
            <TradesTable rows={group.trades} />
          )}
        </div>
      )}
    </li>
  );
}

function Stat({
  label, value, tone = "neutral",
}: {
  label: string;
  value: React.ReactNode;
  tone?: "neutral" | "ok" | "bad";
}) {
  const toneCls = {
    neutral: "text-ink",
    ok: "text-emerald-600 dark:text-emerald-400",
    bad: "text-rose-600 dark:text-rose-400",
  }[tone];
  return (
    <div className="rounded-md border border-line2 bg-bg px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-muted">{label}</div>
      <div className={`mt-0.5 font-semibold ${toneCls}`}>{value}</div>
    </div>
  );
}
