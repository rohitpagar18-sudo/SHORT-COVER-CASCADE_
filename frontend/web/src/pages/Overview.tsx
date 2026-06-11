import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Wifi, BellRing, ShoppingCart, FileText, TrendingUp, AlertTriangle,
  Calendar, RefreshCw, FileBarChart, Send,
} from "lucide-react";
import { api, type Overview as OverviewT } from "../lib/api";
import { Card, CardTitle, StatTile, Skeleton } from "../components/Card";
import ProgressBar from "../components/ProgressBar";
import { inr, pct, hhmm } from "../lib/format";

const POLL_MS = 15_000;

function onOff(v: boolean) {
  return v ? "ON" : "OFF";
}

export default function OverviewPage({
  onData,
}: {
  onData?: (d: OverviewT) => void;
}) {
  const [data, setData] = useState<OverviewT | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const nav = useNavigate();

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;

    const tick = async () => {
      try {
        const d = await api.overview();
        if (!alive) return;
        setData(d);
        setErr(null);
        onData?.(d);
      } catch (e: any) {
        if (!alive) return;
        setErr(e?.message ?? "failed to load");
      } finally {
        if (alive) timer = window.setTimeout(tick, POLL_MS);
      }
    };
    tick();

    return () => {
      alive = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [onData]);

  if (!data && !err) return <OverviewSkeleton />;
  if (!data && err) {
    return (
      <div className="rounded-md border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
        Failed to load overview: {err}
      </div>
    );
  }
  const d = data!;

  const slPct = pct(d.circuit_breakers.sl_count, d.circuit_breakers.max_sl_per_day);
  const lossPct = pct(d.circuit_breakers.daily_loss, d.circuit_breakers.max_loss_per_day);

  return (
    <div className="space-y-4">
      {/* Row 1: feed + modes */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Active Feed"
          value={<span className="flex items-center gap-2"><Wifi className="h-5 w-5" />{d.feed.active_feed.toUpperCase()}</span>}
          tone={d.feed.status === "RUNNING" ? "ok" : "neutral"}
          sub={d.feed.status}
        />
        <StatTile
          label="Alert Mode"
          value={<span className="flex items-center gap-2"><BellRing className="h-5 w-5" />{onOff(d.modes.alert_mode)}</span>}
          tone={d.modes.alert_mode ? "ok" : "off"}
        />
        <StatTile
          label="Order Place Mode"
          value={<span className="flex items-center gap-2"><ShoppingCart className="h-5 w-5" />{onOff(d.modes.order_place_mode)}</span>}
          tone={d.modes.order_place_mode ? "warn" : "off"}
          sub={d.modes.order_place_mode ? "live orders enabled" : "alert-only"}
        />
        <StatTile
          label="Paper Trade Mode"
          value={<span className="flex items-center gap-2"><FileText className="h-5 w-5" />{onOff(d.modes.paper_trade_mode)}</span>}
          tone={d.modes.paper_trade_mode ? "ok" : "off"}
        />
      </div>

      {/* Row 2: instruments + lot caps */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="NIFTY"
          value={onOff(d.instruments.nifty_enabled)}
          tone={d.instruments.nifty_enabled ? "ok" : "off"}
          sub={`Lot size: ${d.instruments.nifty_lot_size ?? "—"}`}
        />
        <StatTile
          label="BankNifty"
          value={onOff(d.instruments.banknifty_enabled)}
          tone={d.instruments.banknifty_enabled ? "ok" : "off"}
          sub={`Lot size: ${d.instruments.banknifty_lot_size ?? "—"}`}
        />
        <StatTile
          label="Max Lots NIFTY"
          value={d.position.nifty_max_lots ?? "—"}
          sub={d.position.lot_cap_enabled ? "cap enforced" : "cap OFF"}
        />
        <StatTile
          label="Max Lots BankNifty"
          value={d.position.banknifty_max_lots ?? "—"}
          sub={d.position.lot_cap_enabled ? "cap enforced" : "cap OFF"}
        />
      </div>

      {/* Three-column band: today / circuit breakers / next events */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <Card>
          <CardTitle>Today's Status</CardTitle>
          <ul className="space-y-2 text-sm">
            <Row icon={<Calendar className="h-4 w-4 text-muted" />} label="Date (IST)" value={d.today.date_ist} />
            <Row label="Market" value={<Badge tone={d.today.market_status === "OPEN" ? "ok" : "neutral"}>{d.today.market_status}</Badge>} />
            <Row label="Current Time" value={d.today.current_time_ist} />
            <Row label="Gap Day" value={d.today.gap_day ? <Badge tone="warn">YES</Badge> : <span className="text-muted">No</span>} />
            <Row label="Signals Today" value={d.today.signals_today} />
            <Row label="Positions Open" value={d.today.positions_open} />
            <Row
              icon={<TrendingUp className="h-4 w-4 text-muted" />}
              label="Paper P&L"
              value={
                <span className={d.today.paper_pnl_today >= 0 ? "text-emerald-600" : "text-rose-600"}>
                  {inr(d.today.paper_pnl_today)}
                </span>
              }
            />
          </ul>
        </Card>

        <Card>
          <CardTitle>
            <span className="flex items-center gap-2"><AlertTriangle className="h-4 w-4 text-amber-500" />Circuit Breakers</span>
          </CardTitle>
          <div className="space-y-4 text-sm">
            <div>
              <div className="mb-1 flex justify-between">
                <span>SL Count</span>
                <span className="text-muted">{d.circuit_breakers.sl_count} / {d.circuit_breakers.max_sl_per_day}</span>
              </div>
              <ProgressBar pct={slPct} tone={slPct >= 100 ? "bad" : slPct >= 66 ? "warn" : "ok"} />
            </div>
            <div>
              <div className="mb-1 flex justify-between">
                <span>Daily Loss</span>
                <span className="text-muted">{inr(d.circuit_breakers.daily_loss)} / {inr(d.circuit_breakers.max_loss_per_day)}</span>
              </div>
              <ProgressBar pct={lossPct} tone={lossPct >= 100 ? "bad" : lossPct >= 66 ? "warn" : "ok"} />
            </div>
          </div>
        </Card>

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
      </div>

      {/* Recent alerts + quick actions */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardTitle>Recent Alerts (Last 5)</CardTitle>
          {d.recent_alerts.length === 0 ? (
            <div className="py-6 text-center text-sm text-muted">No alerts yet today.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase text-muted">
                  <tr>
                    <th className="py-2 pr-4">Time</th>
                    <th className="py-2 pr-4">Symbol</th>
                    <th className="py-2 pr-4">Strike</th>
                    <th className="py-2 pr-4">Type</th>
                    <th className="py-2 pr-4">Relation</th>
                    <th className="py-2 pr-4">Conditions</th>
                    <th className="py-2 pr-4">Risk</th>
                    <th className="py-2 pr-4">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {d.recent_alerts.map((a, i) => (
                    <tr key={i} className="border-t border-slate-100">
                      <td className="py-2 pr-4">{a.time || hhmm(a.timestamp_ist)}</td>
                      <td className="py-2 pr-4">{a.symbol}</td>
                      <td className="py-2 pr-4">{a.strike}</td>
                      <td className="py-2 pr-4">{a.option_type}</td>
                      <td className="py-2 pr-4">{a.relation}</td>
                      <td className="py-2 pr-4">
                        <span className="font-mono text-xs">
                          {a.conditions_passed.length}/5
                        </span>
                      </td>
                      <td className="py-2 pr-4">{a.risk != null ? inr(a.risk) : "—"}</td>
                      <td className="py-2 pr-4">
                        <Badge tone={a.status === "ALERT" ? "ok" : "warn"}>{a.status ?? "—"}</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card>
          <CardTitle>Quick Actions</CardTitle>
          <div className="flex flex-col gap-2">
            <button
              onClick={() => nav("/logs")}
              className="flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm hover:bg-slate-50"
            >
              <FileText className="h-4 w-4" />
              View Today's Logs
            </button>
            <DisabledAction icon={<RefreshCw className="h-4 w-4" />} label="Reload Config Now" />
            <DisabledAction icon={<FileBarChart className="h-4 w-4" />} label="Open Dashboard (Excel)" />
            <DisabledAction icon={<Send className="h-4 w-4" />} label="Send Test Telegram" />
          </div>
        </Card>
      </div>

      {err && (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
          Last poll failed: {err}. Showing previous data.
        </div>
      )}
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
    ok: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    warn: "bg-amber-50 text-amber-700 ring-amber-200",
    bad: "bg-rose-50 text-rose-700 ring-rose-200",
    neutral: "bg-slate-100 text-slate-700 ring-slate-200",
  }[tone];
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${cls}`}>
      {children}
    </span>
  );
}

function DisabledAction({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <button
      disabled
      title="Coming in a later phase"
      className="flex cursor-not-allowed items-center gap-2 rounded-md border border-dashed border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-400"
    >
      {icon}
      {label}
    </button>
  );
}

function OverviewSkeleton() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="rounded-xl border border-slate-200 bg-white p-4">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="mt-3 h-6 w-32" />
            <Skeleton className="mt-2 h-3 w-20" />
          </div>
        ))}
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="rounded-xl border border-slate-200 bg-white p-4">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="mt-3 h-6 w-20" />
          </div>
        ))}
      </div>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="rounded-xl border border-slate-200 bg-white p-4">
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
