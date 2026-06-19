import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FileText, FlaskConical, RefreshCw } from "lucide-react";
import { Card, CardTitle, Skeleton } from "../components/Card";
import { api, type ShadowSlResponse } from "../lib/api";
import { fmtDateLong, hhmm } from "../lib/format";

// ---------------------------------------------------------------------------
// IST helpers — match the Paper Trading page so date filters behave the same.
// ---------------------------------------------------------------------------

function todayIST(): string {
  const now = new Date();
  return new Date(now.getTime() + (now.getTimezoneOffset() + 330) * 60_000)
    .toISOString()
    .slice(0, 10);
}

function istWeekBounds(): { from: string; to: string } {
  const now = new Date();
  const ist = new Date(now.getTime() + (now.getTimezoneOffset() + 330) * 60_000);
  const dow = ist.getDay();
  const daysSinceMonday = dow === 0 ? 6 : dow - 1;
  const monday = new Date(ist);
  monday.setDate(ist.getDate() - daysSinceMonday);
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);
  return {
    from: monday.toISOString().slice(0, 10),
    to: sunday.toISOString().slice(0, 10),
  };
}

type Preset = "today" | "week" | "custom";

const POLL_MS = 30_000;

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function fmtR(r: number | null | undefined): string {
  if (r == null || Number.isNaN(r)) return "—";
  const sign = r > 0 ? "+" : "";
  return `${sign}${r.toFixed(2)}R`;
}

function fmtPrice(p: number | null | undefined): string {
  if (p == null || Number.isNaN(p)) return "—";
  return p.toFixed(2);
}

function fmtPct(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `${n.toFixed(1)}%`;
}

function rToneClass(r: number | null | undefined): string {
  if (r == null || Number.isNaN(r)) return "text-muted";
  if (r > 0) return "text-emerald-600 dark:text-emerald-400";
  if (r < 0) return "text-rose-600 dark:text-rose-400";
  return "text-ink";
}

// ---------------------------------------------------------------------------
// Method comparison table
// ---------------------------------------------------------------------------

function MethodComparison({ data }: { data: ShadowSlResponse }) {
  const methods = data.methods;

  // Indices of best Avg R and best Capture Efficiency (highest values).
  // Tie => no highlight.
  const bestAvgIdx = useMemo(() => bestIndex(methods.map((m) => m.avg_r)), [methods]);
  const bestCaptureIdx = useMemo(
    () => bestIndex(methods.map((m) => m.capture_efficiency)),
    [methods],
  );

  if (methods.length === 0) {
    return (
      <Card>
        <CardTitle>Method Comparison</CardTitle>
        <div className="flex h-24 items-center justify-center text-sm text-muted">
          <FlaskConical className="mr-2 h-5 w-5" />
          No shadow data for the selected window. Run
          <code className="mx-1 rounded bg-line2 px-1.5 py-0.5 text-[11px]">
            update_shadow_sl.bat
          </code>
          after a trading day to populate.
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <CardTitle right={<span className="text-muted text-xs">{methods.length} method{methods.length !== 1 ? "s" : ""}</span>}>
        Method Comparison
      </CardTitle>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-line text-muted">
              <th className="px-3 py-2 font-medium">Method</th>
              <th className="px-3 py-2 font-medium">Trades</th>
              <th className="px-3 py-2 font-medium">Win %</th>
              <th className="px-3 py-2 font-medium">Total R</th>
              <th className="px-3 py-2 font-medium">Avg R</th>
              <th className="px-3 py-2 font-medium" title="Median r_multiple among trades whose MFE >= 1.5R">
                Capture Eff
              </th>
              <th className="px-3 py-2 font-medium">Time-Stop Exits</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line2">
            {methods.map((m, i) => {
              const winAvg = i === bestAvgIdx;
              const winCap = i === bestCaptureIdx;
              return (
                <tr key={m.method} className="hover:bg-bg transition-colors">
                  <td className="px-3 py-2 font-mono text-ink">{m.method}</td>
                  <td className="px-3 py-2 text-ink">{m.trades}</td>
                  <td className="px-3 py-2 text-ink">{fmtPct(m.win_rate)}</td>
                  <td className={`px-3 py-2 ${rToneClass(m.total_r)}`}>{fmtR(m.total_r)}</td>
                  <td
                    className={`px-3 py-2 ${rToneClass(m.avg_r)} ${
                      winAvg ? "bg-emerald-50 dark:bg-emerald-950/30 font-semibold" : ""
                    }`}
                    title={winAvg ? "Best Avg R in the window" : undefined}
                  >
                    {fmtR(m.avg_r)}
                  </td>
                  <td
                    className={`px-3 py-2 ${rToneClass(m.capture_efficiency)} ${
                      winCap ? "bg-emerald-50 dark:bg-emerald-950/30 font-semibold" : ""
                    }`}
                    title={winCap ? "Best Capture Efficiency in the window" : undefined}
                  >
                    {fmtR(m.capture_efficiency)}
                  </td>
                  <td className="px-3 py-2 text-ink">{m.time_stop_exits}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function bestIndex(values: Array<number | null>): number {
  let best = -Infinity;
  let bestIdx = -1;
  let bestCount = 0;
  values.forEach((v, i) => {
    if (v == null || Number.isNaN(v)) return;
    if (v > best) {
      best = v;
      bestIdx = i;
      bestCount = 1;
    } else if (v === best) {
      bestCount += 1;
    }
  });
  return bestCount === 1 ? bestIdx : -1;
}

// ---------------------------------------------------------------------------
// Per-day trade tables — one row per trade, methods pivoted into columns.
// ---------------------------------------------------------------------------

function DayTable({
  date,
  trades,
  methodNames,
}: {
  date: string;
  trades: ShadowSlResponse["days"][number]["trades"];
  methodNames: string[];
}) {
  return (
    <Card>
      <CardTitle right={<span className="text-muted text-xs">{trades.length} trade{trades.length !== 1 ? "s" : ""}</span>}>
        {fmtDateLong(date)}
      </CardTitle>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-[11px]">
          <thead>
            <tr className="border-b border-line text-muted">
              <th className="px-2 py-2 font-medium sticky left-0 bg-card">Time</th>
              <th className="px-2 py-2 font-medium">Symbol</th>
              <th className="px-2 py-2 font-medium">Strike</th>
              <th className="px-2 py-2 font-medium">Type</th>
              <th className="px-2 py-2 font-medium">Relation</th>
              {methodNames.map((name) => (
                <th
                  key={name}
                  colSpan={4}
                  className="px-2 py-2 font-mono text-center border-l border-line"
                >
                  {name}
                </th>
              ))}
            </tr>
            <tr className="border-b border-line text-muted">
              <th className="px-2 py-1 sticky left-0 bg-card" />
              <th className="px-2 py-1" />
              <th className="px-2 py-1" />
              <th className="px-2 py-1" />
              <th className="px-2 py-1" />
              {methodNames.map((name) => (
                <SubHeader key={name} />
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line2">
            {trades.map((t, ti) => {
              const tradeKey = `${t.entry_time}-${t.symbol}-${t.strike}-${t.option_type}-${ti}`;
              return (
                <tr key={tradeKey} className="hover:bg-bg transition-colors">
                  <td className="px-2 py-2 text-muted whitespace-nowrap sticky left-0 bg-card">
                    {hhmm(t.entry_time)}
                  </td>
                  <td className="px-2 py-2 font-medium text-ink">{t.symbol ?? "—"}</td>
                  <td className="px-2 py-2 text-ink">{t.strike ?? "—"}</td>
                  <td className="px-2 py-2 text-ink">{t.option_type ?? "—"}</td>
                  <td className="px-2 py-2 text-ink">{t.relation ?? "—"}</td>
                  {methodNames.map((name) => {
                    const m = t.per_method[name];
                    if (!m) {
                      return (
                        <MethodCells
                          key={`${tradeKey}-${name}`}
                          exit="—"
                          sl="—"
                          tp="—"
                          r={null}
                          reason={null}
                        />
                      );
                    }
                    const tpLabel =
                      m.tp1 != null && m.tp2 != null
                        ? `${fmtPrice(m.tp1)} / ${fmtPrice(m.tp2)}`
                        : "—";
                    return (
                      <MethodCells
                        key={`${tradeKey}-${name}`}
                        exit={fmtPrice(m.exit_price)}
                        sl={fmtPrice(m.initial_sl)}
                        tp={tpLabel}
                        r={m.r_multiple}
                        reason={m.exit_reason}
                      />
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function SubHeader() {
  return (
    <>
      <th className="px-2 py-1 font-normal border-l border-line">Exit</th>
      <th className="px-2 py-1 font-normal">SL</th>
      <th className="px-2 py-1 font-normal">TP</th>
      <th className="px-2 py-1 font-normal">R</th>
    </>
  );
}

function MethodCells({
  exit,
  sl,
  tp,
  r,
  reason,
}: {
  exit: string;
  sl: string;
  tp: string;
  r: number | null;
  reason: string | null;
}) {
  return (
    <>
      <td className="px-2 py-2 text-ink whitespace-nowrap border-l border-line">
        <span title={reason ?? undefined}>{exit}</span>
      </td>
      <td className="px-2 py-2 text-ink whitespace-nowrap">{sl}</td>
      <td className="px-2 py-2 text-ink whitespace-nowrap">{tp}</td>
      <td className={`px-2 py-2 whitespace-nowrap font-semibold ${rToneClass(r)}`}>
        {fmtR(r)}
      </td>
    </>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ShadowStopLoss() {
  const [dateFrom, setDateFrom] = useState<string>(todayIST());
  const [dateTo, setDateTo] = useState<string>(todayIST());
  const [preset, setPreset] = useState<Preset>("today");
  const [data, setData] = useState<ShadowSlResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const lastGoodRef = useRef<ShadowSlResponse | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const result = await api.shadowSl({ date_from: dateFrom, date_to: dateTo });
      setData(result);
      lastGoodRef.current = result;
      setErr(null);
    } catch (e: unknown) {
      setErr((e as Error)?.message ?? "failed to load");
      // Keep the last good payload visible — do NOT clear `data`.
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Poll every 30s.
  useEffect(() => {
    const id = window.setInterval(() => fetchData(), POLL_MS);
    return () => window.clearInterval(id);
  }, [fetchData]);

  function applyPreset(p: Preset) {
    setPreset(p);
    if (p === "today") {
      const t = todayIST();
      setDateFrom(t);
      setDateTo(t);
    } else if (p === "week") {
      const { from, to } = istWeekBounds();
      setDateFrom(from);
      setDateTo(to);
    }
  }

  // Union of all method names across the comparison table — defines column order.
  const methodNames = useMemo(() => {
    if (!data) return [];
    return data.methods.map((m) => m.method);
  }, [data]);

  return (
    <div className="space-y-4">
      <Card>
        <CardTitle
          right={
            <span className="text-muted text-xs">
              {data?.date_from && data.date_to
                ? `${data.date_from} → ${data.date_to}`
                : "—"}
            </span>
          }
        >
          <span className="flex items-center gap-2">
            <FlaskConical className="h-4 w-4 text-amber-500" />
            Stop-Loss Lab
          </span>
        </CardTitle>

        <div className="flex flex-wrap items-end gap-3">
          <div className="flex gap-1">
            {(["today", "week", "custom"] as Preset[]).map((p) => (
              <button
                key={p}
                onClick={() => applyPreset(p)}
                className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                  preset === p
                    ? "bg-accent text-white"
                    : "bg-line2 text-ink hover:bg-line"
                }`}
              >
                {p === "today" ? "Today" : p === "week" ? "This Week" : "Custom"}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1">
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => { setDateFrom(e.target.value); setPreset("custom"); }}
              className="rounded-md border border-line bg-card px-2 py-1 text-xs text-ink focus:outline-none focus:ring-1 focus:ring-accent"
            />
            <span className="text-xs text-muted">to</span>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => { setDateTo(e.target.value); setPreset("custom"); }}
              className="rounded-md border border-line bg-card px-2 py-1 text-xs text-ink focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>
          <button
            onClick={fetchData}
            className="flex items-center gap-1 rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 transition-opacity"
          >
            <RefreshCw className="h-3 w-3" />
            Refresh
          </button>
        </div>

        {err && (
          <div className="mt-3 rounded-md border border-rose-200 bg-rose-50 p-2 text-xs text-rose-700 dark:bg-rose-950/40 dark:text-rose-200">
            Failed to refresh: {err} — showing last successful payload.
          </div>
        )}
      </Card>

      {loading && !data ? (
        <>
          <Card>
            <Skeleton className="h-32 w-full" />
          </Card>
          <Card>
            <Skeleton className="h-48 w-full" />
          </Card>
        </>
      ) : data ? (
        <>
          <MethodComparison data={data} />

          {data.days.length === 0 ? (
            <Card>
              <div className="flex h-32 items-center justify-center text-sm text-muted">
                <FileText className="mr-2 h-5 w-5" />
                No trades in the selected date range.
              </div>
            </Card>
          ) : (
            data.days.map((day) => (
              <DayTable
                key={day.date}
                date={day.date}
                trades={day.trades}
                methodNames={methodNames}
              />
            ))
          )}
        </>
      ) : null}

      <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-200">
        Shadow simulation only — does not affect real or paper trades. IST.
      </div>
    </div>
  );
}
