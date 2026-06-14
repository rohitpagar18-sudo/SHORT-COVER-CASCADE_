import { useEffect, useRef, useState } from "react";
import { Activity, Clock, TrendingUp } from "lucide-react";
import { Card, CardTitle } from "../Card";
import PriceSparkline from "../charts/PriceSparkline";
import { api, type LivePosition, type OpenPositionsResponse } from "../../lib/api";
import { fmtClock, hhmm, inr, inrSigned } from "../../lib/format";

function todayISTDate(): string {
  const now = new Date();
  return new Date(now.getTime() + (now.getTimezoneOffset() + 330) * 60_000)
    .toISOString()
    .slice(0, 10);
}

function entryDateIST(entry_time: string | null): string | null {
  if (!entry_time) return null;
  return entry_time.slice(0, 10);
}

type Props = {
  pollMs?: number;
  showTitle?: boolean;
  emptyMessage?: string;
};

const DEFAULT_POLL = 15_000;

export default function OpenPositionTracker({
  pollMs = DEFAULT_POLL,
  showTitle = true,
  emptyMessage = "No open paper positions.",
}: Props) {
  const [data, setData] = useState<OpenPositionsResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const d = await api.openPositions();
        if (!alive.current) return;
        setData(d);
        setErr(null);
      } catch (e: unknown) {
        if (!alive.current) return;
        setErr((e as Error)?.message ?? "failed to load");
      } finally {
        if (alive.current) timer = window.setTimeout(tick, pollMs);
      }
    };
    tick();
    return () => {
      alive.current = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [pollMs]);

  const positions = data?.positions ?? [];
  const asOf = data?.as_of ?? null;

  const body = (() => {
    if (!data && err) {
      return (
        <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700 dark:bg-rose-950/40 dark:text-rose-200">
          Failed to load open positions: {err}
        </div>
      );
    }
    if (!data) {
      return <div className="text-sm text-muted">Loading…</div>;
    }
    if (positions.length === 0) {
      return (
        <div className="flex h-[160px] flex-col items-center justify-center text-sm text-muted">
          <Activity className="mb-2 h-6 w-6" />
          {emptyMessage}
        </div>
      );
    }
    return (
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        {positions.map((p) => (
          <PositionCard key={`${p.episode_id}-${p.entry_time}`} pos={p} />
        ))}
      </div>
    );
  })();

  if (!showTitle) return <div className="space-y-3">{body}</div>;

  return (
    <Card>
      <CardTitle
        right={
          <span className="flex items-center gap-1 text-xs text-muted">
            <Clock className="h-3 w-3" />
            {asOf ? `as of ${fmtClock(asOf)} IST` : "—"} · updates every 15s
          </span>
        }
      >
        <span className="flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-emerald-500" />
          Open Positions (Live)
        </span>
      </CardTitle>
      {body}
    </Card>
  );
}

function PositionCard({ pos }: { pos: LivePosition }) {
  const ltp = pos.last_ltp;
  const pnl = pos.running_pnl;
  const r = pos.running_pnl_r;
  const isUp = pnl != null && pnl >= 0;

  const entryDate = entryDateIST(pos.entry_time);
  const isToday = entryDate === todayISTDate();
  const dateLabel = !isToday && entryDate ? entryDate.slice(5) : null; // MM-DD if not today

  return (
    <div className="rounded-lg border border-line bg-card p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-sm font-semibold text-ink">
            {pos.symbol} {pos.strike} {pos.option_type}
            {pos.relation && (
              <span className="ml-2 text-xs font-normal text-muted">({pos.relation})</span>
            )}
          </div>
          <div className="text-xs text-muted">
            {dateLabel && <span className="mr-1 font-medium text-amber-600">{dateLabel}</span>}
            Entry {hhmm(pos.entry_time)} · {pos.qty_lots ?? "—"} lot
            {pos.qty_lots === 1 ? "" : "s"}
          </div>
        </div>
        <span className={[
          "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1",
          isToday
            ? "bg-emerald-100 text-emerald-700 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:ring-emerald-900"
            : "bg-amber-100 text-amber-700 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:ring-amber-900",
        ].join(" ")}>
          {isToday && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />}
          {isToday ? "OPEN" : "OPEN (stale)"}
        </span>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
        <Cell label="Buy" value={pos.buy_price != null ? inr(pos.buy_price) : "—"} />
        <Cell
          label={
            <>
              LTP{" "}
              <span className="text-muted">
                {pos.last_ltp_time ? `· ${hhmm(pos.last_ltp_time)}` : ""}
              </span>
            </>
          }
          value={ltp != null ? inr(ltp) : "—"}
          tone={ltp == null ? "muted" : isUp ? "ok" : "bad"}
        />
        <Cell
          label="P&L"
          value={
            pnl == null
              ? "—"
              : `${inrSigned(pnl)}${r != null ? `  (${r >= 0 ? "+" : ""}${r}R)` : ""}`
          }
          tone={pnl == null ? "muted" : isUp ? "ok" : "bad"}
        />
        <Cell label="SL" value={pos.sl != null ? inr(pos.sl) : "—"} />
        <Cell label="TP1" value={pos.tp1 != null ? inr(pos.tp1) : "—"} />
        <Cell label="TP2" value={pos.tp2 != null ? inr(pos.tp2) : "—"} />
      </div>

      <div className="mt-3">
        <SlEntryTpBar pos={pos} />
      </div>

      <div className="mt-3">
        <PriceSparkline
          data={pos.price_series.map((s) => ({ t: s.time, price: s.price }))}
          height={60}
        />
      </div>
    </div>
  );
}

function Cell({
  label,
  value,
  tone = "neutral",
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  tone?: "neutral" | "ok" | "bad" | "muted";
}) {
  const toneCls = {
    neutral: "text-ink",
    ok: "text-emerald-600 dark:text-emerald-400",
    bad: "text-rose-600 dark:text-rose-400",
    muted: "text-muted",
  }[tone];
  return (
    <div className="rounded-md border border-line2 bg-bg px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-muted">{label}</div>
      <div className={`mt-0.5 text-sm font-semibold ${toneCls}`}>{value}</div>
    </div>
  );
}

/**
 * Horizontal bar spanning SL → entry → TP1 → TP2 with a triangle marker
 * pinned at the current LTP. Pure CSS, no recharts — kept tiny so the
 * card stays under ~280px tall.
 */
function SlEntryTpBar({ pos }: { pos: LivePosition }) {
  const sl = pos.sl;
  const entry = pos.buy_price;
  const tp1 = pos.tp1;
  const tp2 = pos.tp2;
  const ltp = pos.last_ltp;

  if (sl == null || entry == null || tp1 == null || tp2 == null) {
    return (
      <div className="rounded-md border border-dashed border-line2 px-2 py-2 text-[11px] text-muted">
        SL / entry / TP not available — cannot draw track.
      </div>
    );
  }
  const lo = Math.min(sl, entry, tp1, tp2, ltp ?? entry);
  const hi = Math.max(sl, entry, tp1, tp2, ltp ?? entry);
  const span = Math.max(hi - lo, 0.0001);
  const pct = (v: number) => ((v - lo) / span) * 100;

  const entryPct = pct(entry);
  const slPct = pct(sl);
  const tp1Pct = pct(tp1);
  const tp2Pct = pct(tp2);
  const ltpPct = ltp != null ? pct(ltp) : null;

  return (
    <div className="space-y-1.5">
      <div className="relative h-2 w-full rounded-full bg-line2">
        {/* Risk leg: SL → entry (rose) */}
        <div
          className="absolute top-0 h-full rounded-l-full bg-rose-300/70 dark:bg-rose-900/60"
          style={{
            left: `${Math.min(slPct, entryPct)}%`,
            width: `${Math.abs(entryPct - slPct)}%`,
          }}
        />
        {/* Reward leg: entry → TP2 (emerald) */}
        <div
          className="absolute top-0 h-full bg-emerald-300/70 dark:bg-emerald-900/60"
          style={{
            left: `${Math.min(entryPct, tp2Pct)}%`,
            width: `${Math.abs(tp2Pct - entryPct)}%`,
          }}
        />
        {/* Stop markers */}
        <Tick at={slPct} color="bg-rose-500" />
        <Tick at={entryPct} color="bg-slate-500" />
        <Tick at={tp1Pct} color="bg-emerald-500" />
        <Tick at={tp2Pct} color="bg-emerald-600" />
        {/* LTP marker (triangle) */}
        {ltpPct != null && (
          <div
            className="absolute -top-1.5 -translate-x-1/2"
            style={{ left: `${ltpPct}%` }}
            title={`LTP ${inr(ltp ?? 0)}`}
          >
            <div className="h-0 w-0 border-x-[5px] border-t-[7px] border-x-transparent border-t-sky-500" />
          </div>
        )}
      </div>
      <div className="flex justify-between text-[10px] text-muted">
        <span>SL {inr(sl)}</span>
        <span>Entry {inr(entry)}</span>
        <span>TP1 {inr(tp1)}</span>
        <span>TP2 {inr(tp2)}</span>
      </div>
    </div>
  );
}

function Tick({ at, color }: { at: number; color: string }) {
  return (
    <div
      className={`absolute top-0 h-2 w-0.5 ${color}`}
      style={{ left: `calc(${at}% - 1px)` }}
    />
  );
}
