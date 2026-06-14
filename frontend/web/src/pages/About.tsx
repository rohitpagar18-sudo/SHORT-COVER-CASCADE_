import { useEffect, useState } from "react";
import { CheckCircle2, ExternalLink, Github, Info, Server, ShieldAlert, XCircle } from "lucide-react";
import { Card, CardTitle } from "../components/Card";
import { api, type ApiHealth } from "../lib/api";

const FRONTEND_VERSION = "1.0.0-F8";
const BOT_PHASE = "Phase 6 — live alert-only validation";

export default function AboutPage() {
  const [health, setHealth] = useState<ApiHealth | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const h = await api.apiHealth();
        if (!alive) return;
        setHealth(h);
        setErr(null);
      } catch (e) {
        if (!alive) return;
        setHealth(null);
        setErr((e as Error)?.message ?? "unreachable");
      } finally {
        if (alive) timer = window.setTimeout(tick, 15_000);
      }
    };
    tick();
    return () => {
      alive = false;
      if (timer) window.clearTimeout(timer);
    };
  }, []);

  const apiUp = health?.ok === true;
  const configPresent = health?.config_present === true;

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-emerald-100 p-2 text-emerald-600 dark:bg-emerald-950/40 dark:text-emerald-400">
            <Info className="h-5 w-5" />
          </div>
          <div className="flex-1">
            <h2 className="text-base font-semibold text-ink">Short Cover Cascade Bot — Dashboard</h2>
            <p className="mt-0.5 text-xs text-muted">
              Read-only dashboard over the bot's own output files. Config edits via the Configuration
              pages are the only writes performed by this dashboard.
            </p>
            <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
              <Row label="Frontend version" value={FRONTEND_VERSION} mono />
              <Row label="Bot phase" value={BOT_PHASE} />
            </div>
          </div>
        </div>
      </Card>

      <Card>
        <CardTitle
          right={
            <span className="text-xs text-muted">re-checks every 15s</span>
          }
        >
          <span className="flex items-center gap-2">
            <Server className="h-4 w-4 text-sky-500" />
            API Health
          </span>
        </CardTitle>
        {apiUp ? (
          <div className="flex items-start gap-2 text-sm text-emerald-600 dark:text-emerald-400">
            <CheckCircle2 className="mt-0.5 h-4 w-4" />
            <div>
              <div className="font-semibold">/api/health · OK</div>
              <div className="text-xs text-muted">
                Server time: {health?.now_ist ?? "—"} ·{" "}
                {configPresent ? "config.yaml present" : "config.yaml MISSING"}
              </div>
              {health?.project_root && (
                <div className="mt-0.5 truncate text-[11px] text-muted">
                  Root: <code className="font-mono">{health.project_root}</code>
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="flex items-start gap-2 text-sm text-rose-600 dark:text-rose-400">
            <XCircle className="mt-0.5 h-4 w-4" />
            <div>
              <div className="font-semibold">API unreachable</div>
              <div className="text-xs text-muted">{err ?? "no response"}</div>
            </div>
          </div>
        )}
      </Card>

      <Card>
        <CardTitle>
          <span className="flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-amber-500" />
            Honest disclaimers
          </span>
        </CardTitle>
        <ul className="space-y-2 text-sm text-ink">
          <li className="rounded-md border border-line2 bg-bg px-3 py-2">
            Paper P&L only — positions update each 5-min scan; outcomes finalize at EOD.
          </li>
          <li className="rounded-md border border-line2 bg-bg px-3 py-2">
            This dashboard reads the bot's files and does not place orders. Order placement is a
            future phase (Phase 8) and is gated by{" "}
            <code className="font-mono">mode.order_place_mode</code> in config.yaml.
          </li>
          <li className="rounded-md border border-line2 bg-bg px-3 py-2">
            Heartbeat fields (uptime, next health check) require a later backend addition. Until
            then the UI displays "—" with a tooltip — never a fabricated value.
          </li>
        </ul>
      </Card>

      <Card>
        <CardTitle>Resources</CardTitle>
        <div className="space-y-2 text-sm">
          <a
            href="/api/health"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 rounded-md border border-line2 bg-bg px-3 py-2 hover:bg-line2"
          >
            <ExternalLink className="h-4 w-4 text-muted" />
            <span className="text-ink">Open /api/health JSON</span>
          </a>
          <a
            href="https://github.com/anthropics/claude-code/issues"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 rounded-md border border-line2 bg-bg px-3 py-2 hover:bg-line2"
          >
            <Github className="h-4 w-4 text-muted" />
            <span className="text-ink">Report Claude Code feedback</span>
          </a>
        </div>
      </Card>

      <p className="text-[11px] text-muted">
        All times are IST (Asia/Kolkata). Read-only over <code className="font-mono">logs/</code>
        {" "}and <code className="font-mono">data/</code>; the only writes target{" "}
        <code className="font-mono">config/config.yaml</code>.
      </p>
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-md border border-line2 bg-bg px-3 py-2 text-xs">
      <div className="text-muted">{label}</div>
      <div className={["mt-0.5 text-sm font-semibold text-ink", mono ? "font-mono" : ""].join(" ")}>
        {value}
      </div>
    </div>
  );
}
