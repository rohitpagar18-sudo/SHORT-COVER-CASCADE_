import { NavLink, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, Sliders, Box, Target, ShieldAlert, Coins, Filter,
  ShoppingCart, RotateCcw, Send, FileText, BarChart3, FileBarChart,
  ScrollText, Activity, Settings, Info, Sun, Moon, ExternalLink,
} from "lucide-react";
import type { BotStatus } from "../lib/api";
import { useTheme } from "../context/ThemeContext";
import { timeAgoIST, fmtUptime, fmtClock } from "../lib/format";

type Item = { to: string; label: string; icon: React.ElementType };

// Canonical sidebar order per the v2 spec. Only pages with real
// implementations route there; everything else lands on /coming-soon
// (the ComingSoon component, mounted as a catch-all in App.tsx).
export const MENU: Item[] = [
  { to: "/overview",           label: "Overview",                icon: LayoutDashboard },
  { to: "/trades-performance", label: "Trades & Performance",    icon: BarChart3 },
  { to: "/configuration",      label: "Configuration",           icon: Sliders },
  { to: "/instruments",        label: "Instruments",             icon: Box },
  { to: "/strike-scanning",    label: "Strike & Scanning",       icon: Target },
  { to: "/stop-loss",          label: "Stop Loss",               icon: ShieldAlert },
  { to: "/risk-money",         label: "Risk & Money",            icon: Coins },
  { to: "/conditions",         label: "Conditions",              icon: Filter },
  { to: "/orders",             label: "Orders",                  icon: ShoppingCart },
  { to: "/reentry-rules",      label: "Re-entry Rules",          icon: RotateCcw },
  { to: "/alerts-telegram",    label: "Alerts & Telegram",       icon: Send },
  { to: "/paper-trading",      label: "Paper Trading",           icon: FileText },
  { to: "/dashboard-reports",  label: "Dashboard & Reports",     icon: FileBarChart },
  { to: "/logs",               label: "Logs",                    icon: ScrollText },
  { to: "/bot-status",         label: "Bot Status",              icon: Activity },
  { to: "/settings",           label: "Settings",                icon: Settings },
  { to: "/about",              label: "About",                   icon: Info },
];

export default function Sidebar({ bot }: { bot: BotStatus | null }) {
  const running = bot?.status === "RUNNING";
  const { theme, toggle } = useTheme();
  const nav = useNavigate();

  const uptime = fmtUptime(bot?.uptime_seconds ?? null);
  const lastReload = fmtClock(bot?.last_config_reload_ist ?? null);
  const nextCheck = fmtClock(bot?.next_health_check_ist ?? null);

  return (
    <aside className="fixed left-0 top-0 h-screen w-64 bg-sidebar text-slate-100 flex flex-col">
      <div className="px-5 py-4 border-b border-white/10">
        <div className="text-base font-semibold leading-tight">Short Cover Cascade</div>
        <div className="text-xs text-slate-400">Bot</div>
      </div>

      <nav className="flex-1 overflow-y-auto py-2">
        {MENU.map((it) => {
          const Icon = it.icon;
          return (
            <NavLink
              key={it.to}
              to={it.to}
              className={({ isActive }) =>
                [
                  "flex items-center gap-3 px-4 py-2 text-sm",
                  "text-slate-300 hover:bg-white/5 hover:text-white",
                  isActive
                    ? "bg-white/10 text-white border-l-2 border-emerald-400"
                    : "border-l-2 border-transparent",
                ].join(" ")
              }
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span className="truncate">{it.label}</span>
            </NavLink>
          );
        })}
      </nav>

      <div className="border-t border-white/10 p-3 space-y-2 text-xs">
        <div className="flex items-center gap-2 rounded-md bg-white/5 px-3 py-2">
          <span
            className={[
              "h-2.5 w-2.5 rounded-full",
              running ? "bg-emerald-400" : "bg-slate-500",
            ].join(" ")}
          />
          <div className="flex-1">
            <div className="font-medium text-slate-100">
              {running ? "RUNNING" : "STOPPED"}
            </div>
            <div className="text-slate-400">
              {bot ? timeAgoIST(bot.last_activity_ist) : "—"}
            </div>
          </div>
        </div>

        <Detail label="Uptime" value={uptime}
          tip={bot?.uptime_seconds == null ? "Requires bot heartbeat (later phase)" : undefined} />
        <Detail label="Last Config Reload" value={lastReload}
          tip={bot?.last_config_reload_ist == null ? "Requires bot heartbeat (later phase)" : "From config.yaml mtime"} />
        <Detail label="Next Health Check" value={nextCheck}
          tip={bot?.next_health_check_ist == null ? "Requires bot heartbeat (later phase)" : undefined} />

        <button
          onClick={() => nav("/bot-status")}
          className="flex w-full items-center justify-center gap-1.5 rounded-md border border-white/10 bg-white/5 py-1.5 text-slate-200 hover:bg-white/10"
        >
          <ExternalLink className="h-3.5 w-3.5" />
          View System Health
        </button>

        <button
          onClick={toggle}
          aria-label="Toggle theme"
          className="flex w-full items-center justify-center gap-1.5 rounded-md border border-white/10 bg-white/5 py-1.5 text-slate-200 hover:bg-white/10"
        >
          {theme === "light" ? <Moon className="h-3.5 w-3.5" /> : <Sun className="h-3.5 w-3.5" />}
          {theme === "light" ? "Dark mode" : "Light mode"}
        </button>
      </div>
    </aside>
  );
}

function Detail({ label, value, tip }: { label: string; value: string; tip?: string }) {
  return (
    <div className="flex items-center justify-between gap-2" title={tip}>
      <span className="text-slate-400">{label}</span>
      <span className="text-slate-200">{value}</span>
    </div>
  );
}
