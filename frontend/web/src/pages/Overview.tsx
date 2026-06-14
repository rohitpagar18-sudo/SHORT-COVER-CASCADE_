import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle, RefreshCw, FileBarChart, Send, ListChecks, Activity,
  ShieldAlert, LockKeyhole, CheckCircle2, XCircle, FileText,
} from "lucide-react";
import { api, type Overview as OverviewT } from "../lib/api";
import { Card, CardTitle, Skeleton } from "../components/Card";
import ProgressBar from "../components/ProgressBar";
import PnLChart from "../components/charts/PnLChart";
import ConditionDonut from "../components/charts/ConditionDonut";
import StatPanel from "../components/charts/StatPanel";
import PriceSparkline from "../components/charts/PriceSparkline";
import { useToast } from "../context/ToastContext";
import { inr, inrSigned, pct, hhmm } from "../lib/format";

const POLL_MS = 15_000;

function onOff(v: boolean) {
  return v ? "ON" : "OFF";
}

function StatusChip({
  label, value, sub, tone,
}: { label: string; value: string; sub: string; tone: "ok" | "warn" | "bad" | "off" | "neutral" }) {
  const valCls = {
    ok: "text-emerald-600 dark:text-emerald-400",
    warn: "text-amber-600 dark:text-amber-400",
    bad: "text-rose-600 dark:text-rose-400",
    off: "text-slate-400 dark:text-slate-500",
    neutral: "text-ink",
  }[tone];
  return (
    <div className="flex min-w-[80px] flex-col gap-0.5 px-4 py-3">
      <div className="text-[10px] uppercase tracking-wide text-muted">{label}</div>
      <div className={`text-sm font-bold ${valCls}`}>{value}</div>
      <div className="text-[10px] text-muted">{sub}</div>
    </div>
  );
}

type Props = {
  selectedDate: string;
  reloadTick: number;
  onData?: (d: OverviewT) => void;
};

export default function OverviewPage({ selectedDate, reloadTick, onData }: Props) {
  const [data, setData] = useState<OverviewT | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [pnlWindow, setPnlWindow] = useState<number>(15);
  const nav = useNavigate();
  const toast = useToast();

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;

    const tick = async () => {
      try {
        const d = await api.overview(selectedDate);
        if (!alive) return;
        setData(d);
        setErr(null);
        onData?.(d);
      } catch (e: unknown) {
        if (!alive) return;
        setErr((e as Error)?.message ?? "failed to load");
      } finally {
        if (alive) timer = window.setTimeout(tick, POLL_MS);
      }
    };
    tick();

    return () => {
      alive = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [onData, selectedDate, reloadTick]);

  const slicedDays = useMemo(() => {
    if (!data) return [];
    return data.pnl_series.days.slice(-pnlWindow);
  }, [data, pnlWindow]);

  const slicedCum = useMemo(() => {
    if (!data) return [];
    return data.pnl_series.cumulative.slice(-pnlWindow);
  }, [data, pnlWindow]);

  if (!data && !err) return <OverviewSkeleton />;
  if (!data && err) {
    return (
      <div className="rounded-md border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:bg-rose-950/40 dark:text-rose-200">
        Failed to load overview: {err}
      </div>
    );
  }
  const d = data!;

  const slPct = pct(d.circuit_breakers.sl_count, d.circuit_breakers.max_sl_per_day);
  const lossPct = pct(d.circuit_breakers.daily_loss, d.circuit_breakers.max_loss_per_day);
  const pnlIsPos = d.today.paper_pnl_today >= 0;

  return (
    <div className="space-y-4">
      {/* Row 1 — compact status strip */}
      <div className="rounded-xl border border-line bg-card">
        <div className="flex flex-wrap divide-x divide-line">
          <StatusChip
            label="Active Feed"
            value={d.feed.active_feed.toUpperCase()}
            sub={d.feed.status === "RUNNING" ? "Connected" : "Disconnected"}
            tone={d.feed.status === "RUNNING" ? "ok" : "neutral"}
          />
          <StatusChip
            label="Alert Mode"
            value={onOff(d.modes.alert_mode)}
            sub={d.modes.alert_mode ? "Telegram on" : "Disabled"}
            tone={d.modes.alert_mode ? "ok" : "off"}
          />
          <StatusChip
            label="Order Mode"
            value={onOff(d.modes.order_place_mode)}
            sub={d.modes.order_place_mode ? "Live orders" : "Safe Mode"}
            tone={d.modes.order_place_mode ? "warn" : "off"}
          />
          <StatusChip
            label="Paper Trade"
            value={onOff(d.modes.paper_trade_mode)}
            sub={d.modes.paper_trade_mode ? "Simulating" : "Off"}
            tone={d.modes.paper_trade_mode ? "ok" : "off"}
          />
          <StatusChip
            label="NIFTY"
            value={onOff(d.instruments.nifty_enabled)}
            sub={`Lot ${d.instruments.nifty_lot_size ?? "—"}`}
            tone={d.instruments.nifty_enabled ? "ok" : "off"}
          />
          <StatusChip
            label="BANKNIFTY"
            value={onOff(d.instruments.banknifty_enabled)}
            sub={`Lot ${d.instruments.banknifty_lot_size ?? "—"}`}
            tone={d.instruments.banknifty_enabled ? "ok" : "off"}
          />
          <StatusChip
            label="Today's P&L"
            value={inrSigned(d.today.paper_pnl_today)}
            sub={`${pnlIsPos ? "+" : ""}${d.today.paper_pnl_pct_today.toFixed(2)}%`}
            tone={pnlIsPos ? "ok" : "bad"}
          />
          <StatusChip
            label="Open Positions"
            value={String(d.today.open_positions_count)}
            sub={d.feed.status === "RUNNING" ? "Running" : "Idle"}
            tone={d.today.open_positions_count > 0 ? "ok" : "neutral"}
          />
        </div>
      </div>

      {/* Row 2 */}
      <div className={[
        "grid grid-cols-1 gap-3",
        d.today.market_status === "OPEN" ? "lg:grid-cols-3" : "lg:grid-cols-2",
      ].join(" ")}>
        <Card>
          <CardTitle right={<Badge tone={cbTone(d.circuit_breakers.status)}>{d.circuit_breakers.status}</Badge>}>
            <span className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-500" />
              Circuit Breakers
            </span>
          </CardTitle>
          <div className="space-y-4 text-sm">
            <div>
              <div className="mb-1 flex justify-between">
                <span className="text-muted">SL Count</span>
                <span>{d.circuit_breakers.sl_count} / {d.circuit_breakers.max_sl_per_day || "—"}</span>
              </div>
              <ProgressBar pct={slPct} tone={slPct >= 100 ? "bad" : slPct >= 66 ? "warn" : "ok"} />
            </div>
            <div>
              <div className="mb-1 flex justify-between">
                <span className="text-muted">Daily Loss</span>
                <span>{inr(d.circuit_breakers.daily_loss)} / {inr(d.circuit_breakers.max_loss_per_day)}</span>
              </div>
              <ProgressBar pct={lossPct} tone={lossPct >= 100 ? "bad" : lossPct >= 66 ? "warn" : "ok"} />
            </div>
          </div>
        </Card>

        {d.today.market_status === "OPEN" && (
          <Card>
            <CardTitle>Next Key Events</CardTitle>
            <ul className="space-y-2 text-sm">
              <Row label="Last Entry" value={d.next_events.last_entry_time ?? "—"} />
              <Row label="Soft Square-off" value={d.next_events.soft_squareoff_time ?? "—"} />
              <Row label="Hard Square-off" value={d.next_events.hard_squareoff_time ?? "—"} />
              <Row label="EOD Summary" value={d.next_events.eod_summary_time ?? "—"} />
              <Row label="Dashboard Sync" value={d.next_events.dashboard_sync_time ?? "—"} />
            </ul>
          </Card>
        )}

        <Card>
          <CardTitle>Quick Actions</CardTitle>
          <div className="flex flex-col gap-2">
            <button
              onClick={() => toast.push("Config auto-reloads on the bot's next scan", "info")}
              className="flex items-center gap-2 rounded-md border border-line bg-card px-3 py-2 text-sm hover:bg-line2"
            >
              <RefreshCw className="h-4 w-4" />
              Reload Config Now
            </button>
            <button
              onClick={() => nav("/logs")}
              className="flex items-center gap-2 rounded-md border border-line bg-card px-3 py-2 text-sm hover:bg-line2"
            >
              <FileText className="h-4 w-4" />
              View Today's Logs
            </button>
            <DisabledAction icon={<FileBarChart className="h-4 w-4" />} label="Open Dashboard (Excel)" />
            <DisabledAction icon={<Send className="h-4 w-4" />} label="Send Test Telegram" />
          </div>
        </Card>
      </div>

      {/* Row 3 — recent alerts + daily P&L */}
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardTitle right={<span className="text-muted">Showing {d.recent_alerts.length} most recent</span>}>
            Recent Alerts (Last 5)
          </CardTitle>
          <RecentAlertsTable rows={d.recent_alerts} />
          <ConditionsLegend rows={d.recent_alerts} />
        </Card>

        <Card>
          <CardTitle
            right={
              <select
                value={pnlWindow}
                onChange={(e) => setPnlWindow(parseInt(e.target.value, 10))}
                className="rounded-md border border-line bg-card px-1.5 py-0.5 text-xs text-ink"
              >
                <option value={7}>7 days</option>
                <option value={15}>15 days</option>
                <option value={30}>30 days</option>
              </select>
            }
          >
            Daily P&L Overview (Paper)
          </CardTitle>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_140px]">
            <div>
              <PnLChart days={slicedDays} cumulative={slicedCum} height={220} />
            </div>
            <StatPanel totals={d.pnl_series.totals} />
          </div>
        </Card>
      </div>

      {/* Row 4 */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardTitle>Open Position (Paper)</CardTitle>
          <OpenPositionView pos={d.open_position} />
        </Card>

        <Card>
          <CardTitle>Condition Summary (Today)</CardTitle>
          <ConditionDonut totalScans={d.condition_summary.total_scans} buckets={d.condition_summary.buckets} />
        </Card>

        <Card>
          <CardTitle>
            <span className="flex items-center gap-2">
              <ListChecks className="h-4 w-4" /> Today's Trade Plan (Paper)
            </span>
          </CardTitle>
          <ul className="space-y-2 text-sm">
            <Row label="Trades / day" value={`${d.trade_plan.trades_taken} / ${d.trade_plan.max_trades_per_day || "—"}`} />
            <Row label="Trades remaining" value={d.trade_plan.trades_remaining} />
            <Row label="Daily SL hits" value={`${d.trade_plan.daily_sl_hit} / ${d.trade_plan.max_sl_per_day || "—"}`} />
            <Row label="Same-strike SLs" value={d.trade_plan.same_strike_sl_count} />
            <Row
              label="Cooldown"
              value={d.trade_plan.cooldown_active
                ? <Badge tone="warn">ACTIVE</Badge>
                : <span className="text-muted">Clear</span>}
            />
          </ul>
        </Card>

        <Card>
          <CardTitle>
            <span className="flex items-center gap-2">
              <ShieldAlert className="h-4 w-4" /> Re-entry Status
            </span>
          </CardTitle>
          <ul className="space-y-2 text-sm">
            <Row label="Cooldown window" value={`${d.reentry_status.cooldown_minutes} min`} />
            <Row
              label="Since last SL"
              value={d.reentry_status.minutes_since_last_sl == null
                ? <span className="text-muted">—</span>
                : `${d.reentry_status.minutes_since_last_sl} min`}
            />
            <Row
              label="Same-strike kill"
              value={<Badge tone={d.reentry_status.same_strike_kill_enabled ? "ok" : "neutral"}>{onOff(d.reentry_status.same_strike_kill_enabled)}</Badge>}
            />
            <li>
              <div className="text-muted">Strikes locked today</div>
              {d.reentry_status.strikes_locked_today.length === 0 ? (
                <div className="text-sm text-muted">None</div>
              ) : (
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {d.reentry_status.strikes_locked_today.map((s) => (
                    <span
                      key={s}
                      className="inline-flex items-center gap-1 rounded-full bg-rose-100 px-2 py-0.5 text-xs text-rose-700 dark:bg-rose-950/40 dark:text-rose-200"
                    >
                      <LockKeyhole className="h-3 w-3" />
                      {s}
                    </span>
                  ))}
                </div>
              )}
            </li>
          </ul>
        </Card>
      </div>

      <div className="pt-2 text-center text-xs text-muted">
        All times are IST (Asia/Kolkata). Data auto-refreshes every 5 minutes.
        {err && <span className="ml-2 text-amber-600 dark:text-amber-400">· Last poll failed: {err}</span>}
      </div>
    </div>
  );
}

function Row({
  label, value, icon,
}: { label: string; value: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <li className="flex items-center justify-between gap-3">
      <span className="flex items-center gap-2 text-muted">
        {icon}
        {label}
      </span>
      <span className="font-medium text-ink">{value}</span>
    </li>
  );
}

function Badge({ children, tone }: { children: React.ReactNode; tone: "ok" | "warn" | "bad" | "neutral" }) {
  const cls = {
    ok: "bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:ring-emerald-900",
    warn: "bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:ring-amber-900",
    bad: "bg-rose-50 text-rose-700 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-300 dark:ring-rose-900",
    neutral: "bg-slate-100 text-slate-700 ring-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:ring-slate-700",
  }[tone];
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${cls}`}>
      {children}
    </span>
  );
}

function cbTone(s: string): "ok" | "warn" | "bad" | "neutral" {
  if (s === "TRIPPED") return "bad";
  if (s === "WARN") return "warn";
  if (s === "OK") return "ok";
  return "neutral";
}

function DisabledAction({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <button
      disabled
      title="Coming in a later phase"
      className="flex cursor-not-allowed items-center gap-2 rounded-md border border-dashed border-line bg-line2 px-3 py-2 text-sm text-muted"
    >
      {icon}
      {label}
    </button>
  );
}

function RecentAlertsTable({ rows }: { rows: OverviewT["recent_alerts"] }) {
  if (rows.length === 0) {
    return <div className="py-6 text-center text-sm text-muted">No alerts yet on this date.</div>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs uppercase text-muted">
          <tr className="border-b border-line">
            <th className="py-2 pr-3">Time</th>
            <th className="py-2 pr-3">Symbol</th>
            <th className="py-2 pr-3">Strike</th>
            <th className="py-2 pr-3">Type</th>
            <th className="py-2 pr-3">Conditions</th>
            <th className="py-2 pr-3">Status</th>
            <th className="py-2 pr-3">Risk</th>
            <th className="py-2 pr-3">Notes</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a, i) => (
            <tr key={i} className="border-b border-line2 last:border-0">
              <td className="py-2 pr-3 font-mono text-xs">{a.time || hhmm(a.timestamp_ist)}</td>
              <td className="py-2 pr-3">{a.symbol}</td>
              <td className="py-2 pr-3">{a.strike}</td>
              <td className="py-2 pr-3">{a.option_type}</td>
              <td className="py-2 pr-3">
                <div className="flex items-center gap-1.5">
                  <span className="font-mono text-xs text-muted">
                    {a.conditions_passed_count}/{a.conditions_total || a.conditions.length || "—"}
                  </span>
                  <span className="flex flex-wrap gap-0.5">
                    {a.conditions.map((c) => (
                      <span
                        key={c.name}
                        title={`${c.name} ${c.passed ? "passed" : "failed"}`}
                        className={
                          c.passed
                            ? "inline-flex h-4 min-w-[24px] items-center justify-center rounded-sm bg-emerald-100 px-1 text-[10px] font-semibold text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
                            : "inline-flex h-4 min-w-[24px] items-center justify-center rounded-sm bg-rose-100 px-1 text-[10px] font-semibold text-rose-700 dark:bg-rose-950/40 dark:text-rose-300"
                        }
                      >
                        {c.name}
                      </span>
                    ))}
                  </span>
                </div>
              </td>
              <td className="py-2 pr-3">
                <Badge tone={a.status === "ALERT" ? "ok" : "warn"}>{a.status ?? "—"}</Badge>
              </td>
              <td className="py-2 pr-3">{a.risk != null ? inr(a.risk) : "—"}</td>
              <td className="max-w-[260px] py-2 pr-3 text-xs text-muted">
                <div className="truncate" title={a.notes ?? ""}>{a.notes ?? "—"}</div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ConditionsLegend({ rows }: { rows: OverviewT["recent_alerts"] }) {
  // Derive legend straight from the real condition names in the table —
  // never hardcode. Empty rows => empty legend.
  const seen = new Set<string>();
  rows.forEach((r) => r.conditions.forEach((c) => seen.add(c.name)));
  const names = Array.from(seen).sort();
  if (names.length === 0) return null;
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
      <span className="font-medium text-ink">Legend:</span>
      {names.map((n) => (
        <span key={n} className="inline-flex items-center gap-1 font-mono">
          <span className="rounded-sm bg-emerald-100 px-1 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300">{n}</span>
        </span>
      ))}
      <span className="ml-2 inline-flex items-center gap-1">
        <CheckCircle2 className="h-3 w-3 text-emerald-500" /> passed
        <XCircle className="ml-2 h-3 w-3 text-rose-500" /> failed
      </span>
    </div>
  );
}

function OpenPositionView({ pos }: { pos: OverviewT["open_position"] }) {
  if (!pos) {
    return (
      <div className="flex h-[180px] flex-col items-center justify-center text-sm text-muted">
        <Activity className="mb-2 h-6 w-6" />
        No open paper position.
      </div>
    );
  }
  return (
    <div className="space-y-3 text-sm">
      <div className="flex items-center justify-between">
        <div className="font-semibold text-ink">
          {pos.symbol} {pos.strike} {pos.option_type}
        </div>
        <Badge tone="ok">{pos.status ?? "OPEN"}</Badge>
      </div>
      <ul className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
        <Row label="Entry" value={pos.buy_price != null ? inr(pos.buy_price) : "—"} />
        <Row label="LTP" value={pos.ltp != null ? inr(pos.ltp) : <span className="text-muted">—</span>} />
        <Row label="SL" value={pos.sl != null ? inr(pos.sl) : "—"} />
        <Row label="TP1" value={pos.tp1 != null ? inr(pos.tp1) : "—"} />
        <Row label="TP2" value={pos.tp2 != null ? inr(pos.tp2) : "—"} />
        <Row label="Lots" value={pos.qty_lots ?? "—"} />
        <Row
          label="P&L"
          value={pos.pnl == null
            ? <span className="text-muted">—</span>
            : <span className={pos.pnl >= 0 ? "text-emerald-600" : "text-rose-600"}>{inrSigned(pos.pnl)}</span>}
        />
        <Row label="Relation" value={pos.relation ?? "—"} />
      </ul>
      <PriceSparkline data={pos.price_series} />
      {pos.ltp == null && (
        <div className="text-[11px] text-muted">
          LTP &amp; live P&L are not in paper_trades.jsonl — they will appear once a broker tap is wired up.
        </div>
      )}
    </div>
  );
}

function OverviewSkeleton() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 2xl:grid-cols-8">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="rounded-xl border border-line bg-card p-4">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="mt-3 h-6 w-28" />
            <Skeleton className="mt-2 h-3 w-16" />
          </div>
        ))}
      </div>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="rounded-xl border border-line bg-card p-4">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="mt-3 h-3 w-full" />
            <Skeleton className="mt-2 h-3 w-3/4" />
            <Skeleton className="mt-2 h-3 w-1/2" />
          </div>
        ))}
      </div>
    </div>
  );
}
