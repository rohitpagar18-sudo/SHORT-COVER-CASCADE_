import { useCallback, useEffect, useState } from "react";
import {
  Activity, AlertTriangle, CheckCircle2, Cpu, FileWarning,
  HardDrive, Plug, Radio, RefreshCw, ServerCog, Timer,
} from "lucide-react";
import { Card, CardTitle, Skeleton, StatTile } from "../components/Card";
import { api, type ConfigData, type SystemHealth } from "../lib/api";
import { fmtUptime, hhmm, timeAgoIST } from "../lib/format";
import { usePollIntervalMs } from "../context/SettingsContext";

// Pulled from config.yaml's `time_rules` + `dashboard` sections — see
// frontend/api/app/services/config_service.py for the contract.
type NextEvent = { label: string; value: string; tip?: string };

function buildNextEvents(cfg: ConfigData | null): NextEvent[] {
  const tr = (cfg?.time_rules ?? {}) as Record<string, unknown>;
  const dash = (cfg?.dashboard ?? {}) as Record<string, unknown>;
  const tg = (cfg?.telegram ?? {}) as Record<string, unknown>;
  const eodEnabled = tg.send_eod_summary === true || tg.send_eod_summary === "ON";
  const dashEnabled = dash.auto_trigger_at_1535 === true || dash.auto_trigger_at_1535 === "ON";

  const fmt = (v: unknown): string =>
    typeof v === "string" && v.trim() ? v : "—";

  return [
    { label: "Last Entry", value: fmt(tr.last_entry_time), tip: "No new entries after this time" },
    { label: "Soft Squareoff", value: fmt(tr.soft_squareoff_time), tip: "Start closing open positions" },
    { label: "Hard Squareoff", value: fmt(tr.hard_squareoff_time), tip: "Force-close (cannot be disabled in code)" },
    {
      label: "EOD Summary",
      value: eodEnabled ? "15:30" : "OFF",
      tip: eodEnabled ? "Telegram EOD summary" : "send_eod_summary is OFF",
    },
    {
      label: "Dashboard Sync",
      value: dashEnabled ? "15:35" : "OFF",
      tip: dashEnabled ? "Auto Parquet/Excel sync" : "auto_trigger_at_1535 is OFF",
    },
  ];
}

export default function BotStatusPage() {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [cfg, setCfg] = useState<ConfigData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [stale, setStale] = useState<boolean>(false);
  const pollMs = usePollIntervalMs();

  const fetchAll = useCallback(async () => {
    try {
      const [h, c] = await Promise.all([api.systemHealth(), api.getConfig().catch(() => null)]);
      setHealth(h);
      if (c) setCfg(c);
      setErr(null);
      setStale(false);
    } catch (e) {
      setErr((e as Error)?.message ?? "failed to load");
      setStale(true);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const tick = async () => {
      if (!alive) return;
      await fetchAll();
      if (alive) timer = window.setTimeout(tick, Math.max(pollMs, 5_000));
    };
    tick();
    return () => {
      alive = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [fetchAll, pollMs]);

  if (!health) {
    return (
      <div className="space-y-4">
        <Card>
          <Skeleton className="h-32 w-full" />
        </Card>
        <Card>
          <Skeleton className="h-64 w-full" />
        </Card>
      </div>
    );
  }

  const running = health.bot.status === "RUNNING";
  const feedConnected = health.feed.status === "connected";
  const nextEvents = buildNextEvents(cfg);

  return (
    <div className="space-y-4">
      {stale && err && (
        <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300">
          Stale data — last fetch failed: {err}. Showing previous snapshot.
        </div>
      )}

      <Card>
        <CardTitle
          right={
            <div className="flex items-center gap-2">
              <span>polls every {Math.round(pollMs / 1000)}s</span>
              <button
                onClick={fetchAll}
                className="flex items-center gap-1 rounded-md border border-line bg-card px-2 py-1 text-xs hover:bg-line2"
              >
                <RefreshCw className="h-3 w-3" />
                Refresh
              </button>
            </div>
          }
        >
          <span className="flex items-center gap-2">
            <ServerCog className="h-4 w-4 text-emerald-500" />
            Bot Status
          </span>
        </CardTitle>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          <StatTile
            label="Bot"
            value={running ? "RUNNING" : "STOPPED"}
            tone={running ? "ok" : "bad"}
            sub={timeAgoIST(health.bot.last_activity_ist) + " · last activity"}
            icon={<Activity className="h-4 w-4" />}
          />
          <StatTile
            label="Feed"
            value={(health.feed.active_feed || "—").toUpperCase()}
            tone={feedConnected ? "ok" : "off"}
            sub={feedConnected ? "connected" : "disconnected (bot.log idle)"}
            icon={<Plug className="h-4 w-4" />}
          />
          <StatTile
            label="Uptime"
            value={health.bot.uptime_seconds == null ? "—" : fmtUptime(health.bot.uptime_seconds)}
            tone={health.bot.uptime_seconds == null ? "off" : "neutral"}
            sub={health.bot.uptime_seconds == null ? "needs a bot heartbeat file" : "since process start"}
            icon={<Timer className="h-4 w-4" />}
          />
          <StatTile
            label="Scan Cadence"
            value={health.scan_cadence.healthy ? "Healthy" : "Gaps"}
            tone={health.scan_cadence.healthy ? "ok" : "warn"}
            sub={`expected every ${health.scan_cadence.expected_interval_min}m`}
            icon={<Radio className="h-4 w-4" />}
          />
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardTitle>
            <span className="flex items-center gap-2">
              <Cpu className="h-4 w-4 text-sky-500" />
              Scan Cadence
            </span>
          </CardTitle>
          <p className="mb-3 text-xs text-muted">{health.scan_cadence.note}</p>
          {health.scan_cadence.recent_gaps.length === 0 ? (
            <div className="flex items-center gap-2 text-sm text-emerald-600 dark:text-emerald-400">
              <CheckCircle2 className="h-4 w-4" />
              No gaps detected during market hours.
            </div>
          ) : (
            <div className="overflow-hidden rounded-md border border-line2">
              <table className="min-w-full text-xs">
                <thead className="bg-line2 text-muted">
                  <tr>
                    <th className="px-2 py-1.5 text-left font-semibold">From</th>
                    <th className="px-2 py-1.5 text-left font-semibold">To</th>
                    <th className="px-2 py-1.5 text-right font-semibold">Gap (min)</th>
                  </tr>
                </thead>
                <tbody>
                  {health.scan_cadence.recent_gaps.map((g, i) => (
                    <tr key={i} className="border-t border-line2">
                      <td className="px-2 py-1 font-mono">{hhmm(g.from) ?? g.from}</td>
                      <td className="px-2 py-1 font-mono">{hhmm(g.to) ?? g.to}</td>
                      <td className="px-2 py-1 text-right font-semibold text-amber-600 dark:text-amber-400">
                        {g.gap_min}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card>
          <CardTitle>
            <span className="flex items-center gap-2">
              <Timer className="h-4 w-4 text-amber-500" />
              Next Key Events
            </span>
          </CardTitle>
          <div className="space-y-2">
            {nextEvents.map((e) => (
              <div
                key={e.label}
                className="flex items-center justify-between rounded-md border border-line2 bg-bg px-3 py-2 text-sm"
                title={e.tip}
              >
                <span className="text-muted">{e.label}</span>
                <span className="font-mono font-semibold text-ink">{e.value}</span>
              </div>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-muted">
            Pulled from <code className="font-mono">config.yaml</code> · time_rules + dashboard.
          </p>
        </Card>
      </div>

      <Card>
        <CardTitle>
          <span className="flex items-center gap-2">
            <HardDrive className="h-4 w-4 text-emerald-500" />
            Log Files
          </span>
        </CardTitle>
        <div className="overflow-x-auto rounded-md border border-line2">
          <table className="min-w-full text-xs">
            <thead className="bg-line2 text-muted">
              <tr>
                <th className="px-2 py-1.5 text-left font-semibold">File</th>
                <th className="px-2 py-1.5 text-right font-semibold">Size</th>
                <th className="px-2 py-1.5 text-left font-semibold">Last Modified</th>
                <th className="px-2 py-1.5 text-center font-semibold">Fresh (24h)</th>
              </tr>
            </thead>
            <tbody>
              {health.files.map((f) => (
                <tr key={f.name} className="border-t border-line2">
                  <td className="px-2 py-1.5 font-mono text-ink">{f.name}</td>
                  <td className="px-2 py-1.5 text-right">
                    {f.size_kb == null ? "—" : `${f.size_kb.toLocaleString()} KB`}
                  </td>
                  <td className="px-2 py-1.5">
                    {f.last_modified_ist == null
                      ? "—"
                      : `${timeAgoIST(f.last_modified_ist)} (${f.last_modified_ist.slice(0, 16).replace("T", " ")} IST)`}
                  </td>
                  <td className="px-2 py-1.5 text-center">
                    {f.fresh ? (
                      <span className="text-emerald-500">✓</span>
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[11px] text-muted">
          <code className="font-mono">state.json</code> is created by the bot on first run — its
          absence is normal on a fresh machine.
        </p>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardTitle
            right={
              <span className="text-xs text-muted">
                {health.data_issues.count.toLocaleString()} total
              </span>
            }
          >
            <span className="flex items-center gap-2">
              <FileWarning className="h-4 w-4 text-amber-500" />
              Data Issues
            </span>
          </CardTitle>
          {health.data_issues.recent.length === 0 ? (
            <div className="flex items-center gap-2 text-sm text-emerald-600 dark:text-emerald-400">
              <CheckCircle2 className="h-4 w-4" />
              No data issues recorded.
            </div>
          ) : (
            <div className="space-y-1">
              {health.data_issues.recent.map((i, idx) => (
                <div
                  key={idx}
                  className="rounded-md border border-line2 bg-bg px-2 py-1.5 text-xs"
                >
                  <div className="flex items-center justify-between font-semibold">
                    <span className="text-rose-500">{i.issue_type}</span>
                    <span className="text-muted">{hhmm(i.time)}</span>
                  </div>
                  <div className="mt-1 break-words text-muted">{i.detail || "—"}</div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card>
          <CardTitle>
            <span className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-emerald-500" />
              Recent Activity
            </span>
          </CardTitle>
          <div className="space-y-2 text-sm">
            <Row
              label="Last Config Reload"
              value={
                health.last_config_reload_ist
                  ? `${timeAgoIST(health.last_config_reload_ist)} · ${health.last_config_reload_ist.slice(0, 16).replace("T", " ")} IST`
                  : "—"
              }
              tip="From config.yaml mtime — proxy for the bot's next 5-min reload."
            />
            <Row
              label="Last Dashboard Sync"
              value={
                health.last_dashboard_sync_ist
                  ? `${timeAgoIST(health.last_dashboard_sync_ist)} · ${health.last_dashboard_sync_ist.slice(0, 16).replace("T", " ")} IST`
                  : "—"
              }
              tip="From bot.log — searches reversed lines for 'dashboard' or 'sync'."
            />
            <Row
              label="Last Bot Activity"
              value={
                health.bot.last_activity_ist
                  ? `${timeAgoIST(health.bot.last_activity_ist)} · ${health.bot.last_activity_ist.slice(0, 16).replace("T", " ")} IST`
                  : "—"
              }
              tip="From bot.log mtime."
            />
          </div>
        </Card>
      </div>

      <p className="text-xs text-muted">
        All times are IST (Asia/Kolkata). Bot heartbeat (uptime, next health check) requires a later
        backend addition; until then those fields show "—".
      </p>
    </div>
  );
}

function Row({ label, value, tip }: { label: string; value: string; tip?: string }) {
  return (
    <div
      className="flex items-center justify-between rounded-md border border-line2 bg-bg px-3 py-2"
      title={tip}
    >
      <span className="text-muted">{label}</span>
      <span className="text-right font-mono text-ink">{value}</span>
    </div>
  );
}
