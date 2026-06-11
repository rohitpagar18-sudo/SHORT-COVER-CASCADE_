import { NavLink } from "react-router-dom";
import {
  LayoutDashboard, Sliders, Box, Target, Coins, Filter, ShoppingCart,
  Clock, Send, FileText, BarChart3, ScrollText, FileBarChart, Activity,
  Settings, Info,
} from "lucide-react";
import type { BotStatus } from "../lib/api";
import { timeAgoIST } from "../lib/format";

type Item = { to: string; label: string; icon: React.ElementType };

// Full menu in the exact order requested. Only /overview routes to a
// real page in this phase — others go to the "Coming soon" placeholder.
export const MENU: Item[] = [
  { to: "/overview",           label: "Overview",                icon: LayoutDashboard },
  { to: "/configuration",      label: "Configuration",           icon: Sliders },
  { to: "/instruments",        label: "Instruments",             icon: Box },
  { to: "/strike-scanning",    label: "Strike & Scanning",       icon: Target },
  { to: "/risk-money",         label: "Risk & Money",            icon: Coins },
  { to: "/conditions",         label: "Conditions",              icon: Filter },
  { to: "/orders",             label: "Orders",                  icon: ShoppingCart },
  { to: "/time-reentry",       label: "Time & Re-entry",         icon: Clock },
  { to: "/alerts-telegram",    label: "Alerts & Telegram",       icon: Send },
  { to: "/paper-trading",      label: "Paper Trading",           icon: FileText },
  { to: "/trades-performance", label: "Trades & Performance",    icon: BarChart3 },
  { to: "/logs",               label: "Logs Viewer",             icon: ScrollText },
  { to: "/dashboard-reports",  label: "Dashboard & Reports",     icon: FileBarChart },
  { to: "/bot-status",         label: "Bot Status",              icon: Activity },
  { to: "/settings",           label: "Settings",                icon: Settings },
  { to: "/about",              label: "About",                   icon: Info },
];

export default function Sidebar({ bot }: { bot: BotStatus | null }) {
  const running = bot?.status === "RUNNING";

  return (
    <aside className="fixed left-0 top-0 h-screen w-64 bg-sidebar text-slate-100 flex flex-col">
      <div className="px-5 py-4 border-b border-white/10">
        <div className="text-base font-semibold leading-tight">Short Cover Cascade</div>
        <div className="text-xs text-slate-400">Bot</div>
      </div>

      <nav className="flex-1 overflow-y-auto py-3">
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
                  isActive ? "bg-white/10 text-white border-l-2 border-emerald-400" : "border-l-2 border-transparent",
                ].join(" ")
              }
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span className="truncate">{it.label}</span>
            </NavLink>
          );
        })}
      </nav>

      <div className="border-t border-white/10 p-3">
        <div className="flex items-center gap-2 rounded-md bg-white/5 px-3 py-2">
          <span
            className={[
              "h-2.5 w-2.5 rounded-full",
              running ? "bg-emerald-400" : "bg-slate-500",
            ].join(" ")}
          />
          <div className="text-xs">
            <div className="font-medium">{running ? "RUNNING" : "STOPPED"}</div>
            <div className="text-slate-400">
              {bot ? timeAgoIST(bot.last_activity_ist) : "—"}
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
}
