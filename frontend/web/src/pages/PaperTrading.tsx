import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, FileText, RefreshCw } from "lucide-react";
import { Card, CardTitle, Skeleton, StatTile } from "../components/Card";
import OpenPositionTracker from "../components/positions/OpenPositionTracker";
import {
  api,
  type PaperEpisode,
  type PaperEpisodesResponse,
  type PaperOverridesResponse,
  type PaperTodayResponse,
} from "../lib/api";
import { hhmm, inr, inrSigned } from "../lib/format";

// ---------------------------------------------------------------------------
// IST helpers
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
  const dow = ist.getDay(); // 0=Sun
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

// ---------------------------------------------------------------------------
// Outcome badge
// ---------------------------------------------------------------------------

function OutcomeBadge({ outcome }: { outcome: string | null }) {
  if (!outcome) return <span className="text-muted text-xs">—</span>;
  const map: Record<string, { bg: string; text: string; label: string }> = {
    TP2_HIT: { bg: "bg-emerald-600", text: "text-white", label: "TP2 HIT" },
    TP1_HIT: { bg: "bg-emerald-400", text: "text-white", label: "TP1 HIT" },
    SL_HIT: { bg: "bg-rose-500", text: "text-white", label: "SL HIT" },
    PARTIAL: { bg: "bg-amber-500", text: "text-white", label: "PARTIAL" },
    NO_DATA: { bg: "bg-slate-400", text: "text-white", label: "RUNNING" },
    WOULD_SKIP: { bg: "bg-slate-300", text: "text-slate-700", label: "SKIP" },
  };
  const s = map[outcome] ?? { bg: "bg-slate-300", text: "text-slate-700", label: outcome };
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold ${s.bg} ${s.text}`}>
      {s.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Selection badge
// ---------------------------------------------------------------------------

function SelectionBadge({ selection }: { selection: "TAKEN" | "SKIPPED" | null }) {
  if (!selection) return <span className="text-muted text-xs">—</span>;
  if (selection === "TAKEN")
    return (
      <span className="inline-flex items-center rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300">
        TAKEN
      </span>
    );
  return (
    <span className="inline-flex items-center rounded-full bg-slate-200 px-2 py-0.5 text-[10px] font-semibold text-slate-600 dark:bg-slate-700 dark:text-slate-300">
      SKIPPED
    </span>
  );
}

// ---------------------------------------------------------------------------
// Today's Paper Plan strip
// ---------------------------------------------------------------------------

function PaperPlanStrip({ data }: { data: PaperTodayResponse | null }) {
  if (!data) {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
        {Array.from({ length: 7 }).map((_, i) => (
          <Skeleton key={i} className="h-20" />
        ))}
      </div>
    );
  }
  const { selection: s, reentry: r } = data;
  const cooldownLabel = s.cooldown_active ? "YES" : "NO";
  const cooldownTone = s.cooldown_active ? "warn" : "ok";
  const sameStrikeKillLabel = r.same_strike_kill_enabled ? "ON" : "OFF";
  const sameStrikeKillTone = r.same_strike_kill_enabled ? "warn" : "neutral";
  const lockedStrikes = r.strikes_locked_today.length > 0
    ? r.strikes_locked_today.join(", ")
    : "None";
  const lockedTone = r.strikes_locked_today.length > 0 ? "bad" : "ok";

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
      <StatTile
        label="Max Trades/Day"
        value={s.max_trades_per_day || "—"}
        tone="neutral"
      />
      <StatTile
        label="Taken"
        value={s.trades_taken}
        tone={s.trades_taken > 0 ? "ok" : "neutral"}
      />
      <StatTile
        label="Remaining"
        value={s.max_trades_per_day ? s.trades_remaining : "—"}
        tone={s.trades_remaining === 0 && s.max_trades_per_day > 0 ? "warn" : "neutral"}
      />
      <StatTile
        label="Daily SL Hit"
        value={`${s.daily_sl_hit}${s.max_sl_per_day ? ` / ${s.max_sl_per_day}` : ""}`}
        tone={s.max_sl_per_day && s.daily_sl_hit >= s.max_sl_per_day ? "bad" : s.daily_sl_hit > 0 ? "warn" : "ok"}
      />
      <StatTile
        label="Cooldown Active"
        value={cooldownLabel}
        tone={cooldownTone}
        sub={
          s.cooldown_active && r.minutes_since_last_sl != null
            ? `${r.minutes_since_last_sl}m since SL · ${r.cooldown_minutes}m window`
            : r.cooldown_minutes > 0
            ? `${r.cooldown_minutes}m window`
            : undefined
        }
      />
      <StatTile
        label="Same-Strike Kill"
        value={sameStrikeKillLabel}
        tone={sameStrikeKillTone}
        sub={`Count: ${s.same_strike_sl_count}`}
      />
      <StatTile
        label="Strikes Locked"
        value={lockedStrikes}
        tone={lockedTone}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Episode table row (expandable)
// ---------------------------------------------------------------------------

function EpisodeRow({ ep }: { ep: PaperEpisode }) {
  const [expanded, setExpanded] = useState(false);
  const hasRMetrics =
    ep.mfe_r != null || ep.mae_r != null || ep.max_drawdown_r != null;
  const hasEchoes = ep.echo_count > 0;

  return (
    <>
      <tr
        className="cursor-pointer hover:bg-bg transition-colors"
        onClick={() => setExpanded((x) => !x)}
      >
        <td className="px-3 py-2 text-xs text-muted whitespace-nowrap">
          {expanded ? (
            <ChevronDown className="inline h-3 w-3" />
          ) : (
            <ChevronRight className="inline h-3 w-3" />
          )}{" "}
          {ep.time ?? "—"}
        </td>
        <td className="px-3 py-2 text-xs font-medium text-ink whitespace-nowrap">
          {ep.symbol ?? "—"}
        </td>
        <td className="px-3 py-2 text-xs text-ink whitespace-nowrap">
          {ep.option_type ?? "—"}
        </td>
        <td className="px-3 py-2 text-xs text-ink whitespace-nowrap">
          {ep.strike ?? "—"}
          {ep.relation && (
            <span className="ml-1 text-muted">({ep.relation})</span>
          )}
        </td>
        <td className="px-3 py-2 whitespace-nowrap">
          <SelectionBadge selection={ep.selection} />
          {ep.is_overridden && (
            <span className="ml-1 inline-flex items-center rounded-full bg-amber-100 px-1.5 py-0.5 text-[9px] font-semibold text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
              OVR
            </span>
          )}
        </td>
        <td className="px-3 py-2 text-xs text-muted max-w-[140px] truncate">
          {ep.selection === "SKIPPED" ? (ep.skip_reason ?? "—") : "—"}
        </td>
        <td className="px-3 py-2 text-xs text-ink whitespace-nowrap">
          {ep.entry_price != null ? inr(ep.entry_price) : "—"}
        </td>
        <td className="px-3 py-2 whitespace-nowrap">
          <OutcomeBadge outcome={ep.outcome} />
        </td>
        <td className="px-3 py-2 text-xs text-ink whitespace-nowrap">
          {ep.r_multiple != null
            ? `${ep.r_multiple >= 0 ? "+" : ""}${ep.r_multiple.toFixed(2)}R`
            : "—"}
        </td>
        <td
          className={`px-3 py-2 text-xs font-medium whitespace-nowrap ${
            ep.paper_pnl != null && ep.paper_pnl >= 0
              ? "text-emerald-600 dark:text-emerald-400"
              : ep.paper_pnl != null
              ? "text-rose-600 dark:text-rose-400"
              : "text-muted"
          }`}
        >
          {ep.paper_pnl != null ? inrSigned(ep.paper_pnl) : "—"}
        </td>
      </tr>
      {expanded && (
        <tr className="bg-bg">
          <td colSpan={10} className="px-6 pb-3 pt-1">
            <div className="space-y-3 text-xs">
              {/* Price levels */}
              <div className="flex flex-wrap gap-4 text-muted">
                <span>SL: {ep.sl != null ? inr(ep.sl) : "—"}</span>
                <span>TP1: {ep.tp1 != null ? inr(ep.tp1) : "—"}</span>
                <span>TP2: {ep.tp2 != null ? inr(ep.tp2) : "—"}</span>
                <span>Qty: {ep.qty_lots != null ? `${ep.qty_lots} lot${ep.qty_lots === 1 ? "" : "s"}` : "—"}</span>
              </div>

              {/* R-metrics */}
              {hasRMetrics && (
                <div className="flex flex-wrap gap-4 rounded-md border border-line2 bg-card px-3 py-2">
                  <span className="font-semibold text-ink">R-metrics:</span>
                  {ep.mfe_r != null && (
                    <span className="text-emerald-600 dark:text-emerald-400">
                      MFE: +{ep.mfe_r.toFixed(2)}R
                    </span>
                  )}
                  {ep.mae_r != null && (
                    <span className="text-rose-600 dark:text-rose-400">
                      MAE: {ep.mae_r.toFixed(2)}R
                    </span>
                  )}
                  {ep.max_drawdown_r != null && (
                    <span className="text-amber-600 dark:text-amber-400">
                      Max DD: {ep.max_drawdown_r.toFixed(2)}R
                    </span>
                  )}
                </div>
              )}

              {/* Echoes */}
              {hasEchoes && (
                <div>
                  <span className="font-semibold text-ink">
                    Echoes ({ep.echo_count}):
                  </span>
                  <div className="mt-1 flex flex-wrap gap-2">
                    {ep.echoes.map((e, i) => (
                      <span
                        key={i}
                        className="rounded-md border border-line2 bg-card px-2 py-1 text-muted"
                      >
                        {e.relation ?? "—"} @ {hhmm(e.time)}{" "}
                        {e.price != null ? `· ${inr(e.price)}` : ""}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Episodes table with filters
// ---------------------------------------------------------------------------

type Preset = "today" | "week" | "custom";

function EpisodesSection() {
  const [preset, setPreset] = useState<Preset>("today");
  const [dateFrom, setDateFrom] = useState(todayIST());
  const [dateTo, setDateTo] = useState(todayIST());
  const [statusFilter, setStatusFilter] = useState("");
  const [symbolFilter, setSymbolFilter] = useState("");
  const [optionTypeFilter, setOptionTypeFilter] = useState("");

  const [data, setData] = useState<PaperEpisodesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const result = await api.paperEpisodes({
        date_from: dateFrom,
        date_to: dateTo,
        status: statusFilter || undefined,
        symbol: symbolFilter || undefined,
        option_type: optionTypeFilter || undefined,
      });
      setData(result);
      setErr(null);
    } catch (e: unknown) {
      setErr((e as Error)?.message ?? "failed to load");
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo, statusFilter, symbolFilter, optionTypeFilter]);

  useEffect(() => {
    fetchData();
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
    // custom: user sets dates manually
  }

  const episodes = data?.episodes ?? [];

  return (
    <Card>
      <CardTitle right={<span className="text-muted text-xs">{episodes.length} episode{episodes.length !== 1 ? "s" : ""}</span>}>
        Paper Episodes
      </CardTitle>

      {/* Filter bar */}
      <div className="mb-4 flex flex-wrap items-end gap-3">
        {/* Presets */}
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

        {/* Date range */}
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

        {/* Status filter */}
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-md border border-line bg-card px-2 py-1 text-xs text-ink focus:outline-none focus:ring-1 focus:ring-accent"
        >
          <option value="">All Decisions</option>
          <option value="TAKEN">TAKEN</option>
          <option value="SKIPPED">SKIPPED</option>
        </select>

        {/* Symbol input */}
        <input
          type="text"
          placeholder="Symbol (e.g. NIFTY)"
          value={symbolFilter}
          onChange={(e) => setSymbolFilter(e.target.value.toUpperCase())}
          className="w-36 rounded-md border border-line bg-card px-2 py-1 text-xs text-ink focus:outline-none focus:ring-1 focus:ring-accent"
        />

        {/* Option type filter */}
        <select
          value={optionTypeFilter}
          onChange={(e) => setOptionTypeFilter(e.target.value)}
          className="rounded-md border border-line bg-card px-2 py-1 text-xs text-ink focus:outline-none focus:ring-1 focus:ring-accent"
        >
          <option value="">CE &amp; PE</option>
          <option value="CE">CE only</option>
          <option value="PE">PE only</option>
        </select>

        <button
          onClick={fetchData}
          className="flex items-center gap-1 rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 transition-opacity"
        >
          <RefreshCw className="h-3 w-3" />
          Refresh
        </button>
      </div>

      {/* Error banner (keep last data visible) */}
      {err && (
        <div className="mb-3 rounded-md border border-rose-200 bg-rose-50 p-2 text-xs text-rose-700 dark:bg-rose-950/40 dark:text-rose-200">
          Failed to refresh: {err}
        </div>
      )}

      {/* Table */}
      {loading && !data ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : episodes.length === 0 ? (
        <div className="flex h-32 items-center justify-center text-sm text-muted">
          <FileText className="mr-2 h-5 w-5" />
          No episodes found for the selected filters.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-line text-muted">
                <th className="px-3 py-2 font-medium">Time</th>
                <th className="px-3 py-2 font-medium">Symbol</th>
                <th className="px-3 py-2 font-medium">Type</th>
                <th className="px-3 py-2 font-medium">Strike</th>
                <th className="px-3 py-2 font-medium">Decision</th>
                <th className="px-3 py-2 font-medium">Reason</th>
                <th className="px-3 py-2 font-medium">Entry</th>
                <th className="px-3 py-2 font-medium">Outcome</th>
                <th className="px-3 py-2 font-medium">R</th>
                <th className="px-3 py-2 font-medium">P&amp;L</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line2">
              {episodes.map((ep, idx) => (
                <EpisodeRow key={ep.episode_id ?? idx} ep={ep} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Manual overrides section (collapsible)
// ---------------------------------------------------------------------------

function OverridesSection() {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<PaperOverridesResponse | null>(null);
  const fetchedRef = useRef(false);

  useEffect(() => {
    if (!open || fetchedRef.current) return;
    fetchedRef.current = true;
    api.paperOverrides().then(setData).catch(() => setData({ rows: [], columns: [] }));
  }, [open]);

  return (
    <Card>
      <button
        className="flex w-full items-center justify-between text-sm font-semibold text-ink"
        onClick={() => setOpen((x) => !x)}
      >
        <span className="flex items-center gap-2">
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          Manual Overrides
        </span>
        <span className="text-xs font-normal text-muted">
          {data ? `${data.rows.length} row${data.rows.length !== 1 ? "s" : ""}` : "click to load"}
        </span>
      </button>

      {open && (
        <div className="mt-4">
          <p className="mb-3 text-xs text-muted">
            Manual overrides are user-owned and always win; edit the CSV directly at{" "}
            <code className="rounded bg-line2 px-1 py-0.5 text-[11px]">logs/paper_overrides.csv</code>.
          </p>

          {!data ? (
            <Skeleton className="h-20 w-full" />
          ) : data.rows.length === 0 ? (
            <div className="flex h-16 items-center justify-center text-sm text-muted">
              No manual overrides.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-line text-muted">
                    {data.columns.map((col) => (
                      <th key={col} className="px-3 py-2 font-medium whitespace-nowrap">
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-line2">
                  {data.rows.map((row, idx) => (
                    <tr key={idx} className="hover:bg-bg transition-colors">
                      {data.columns.map((col) => (
                        <td key={col} className="px-3 py-2 text-ink whitespace-nowrap">
                          {row[col] || <span className="text-muted">—</span>}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

const PLAN_POLL_MS = 60_000;

export default function PaperTradingPage() {
  const [planData, setPlanData] = useState<PaperTodayResponse | null>(null);
  const [planErr, setPlanErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const d = await api.paperToday();
        if (!alive) return;
        setPlanData(d);
        setPlanErr(null);
      } catch (e: unknown) {
        if (!alive) return;
        // keep last good data; just surface the error
        setPlanErr((e as Error)?.message ?? "failed to load");
      } finally {
        if (alive) timer = window.setTimeout(tick, PLAN_POLL_MS);
      }
    };
    tick();
    return () => {
      alive = false;
      if (timer) window.clearTimeout(timer);
    };
  }, []);

  return (
    <div className="space-y-6">
      {/* 1. Open Positions (Live) */}
      <OpenPositionTracker showTitle={true} />

      {/* 2. Today's Paper Plan */}
      <Card>
        <CardTitle
          right={
            planErr ? (
              <span className="text-xs text-rose-500">refresh failed: {planErr}</span>
            ) : (
              <span className="text-xs text-muted">refreshes every 60s</span>
            )
          }
        >
          Today's Paper Plan
        </CardTitle>
        <PaperPlanStrip data={planData} />
      </Card>

      {/* 3. Paper Episodes table */}
      <EpisodesSection />

      {/* 4. Manual Overrides (collapsible) */}
      <OverridesSection />

      {/* 5. Footer */}
      <p className="text-center text-xs text-muted pb-4">
        All times are IST (Asia/Kolkata). Paper P&amp;L; positions update each 5-min scan,
        outcomes finalize at EOD.
      </p>
    </div>
  );
}
