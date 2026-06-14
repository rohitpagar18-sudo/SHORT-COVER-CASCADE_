import { useCallback, useEffect, useMemo, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import Sidebar, { MENU } from "./components/Sidebar";
import Header from "./components/Header";
import ComingSoon from "./components/ComingSoon";
import OverviewPage from "./pages/Overview";
import ConfigurationPage from "./pages/Configuration";
import TradesPerformancePage from "./pages/TradesPerformance";
import PaperTradingPage from "./pages/PaperTrading";
import DashboardReportsPage from "./pages/DashboardReports";
import { api, type BotStatus, type Overview } from "./lib/api";
import { useToast } from "./context/ToastContext";

const BOT_POLL_MS = 15_000;

function todayISTISO(): string {
  const now = new Date();
  const ist = new Date(now.getTime() + (now.getTimezoneOffset() + 330) * 60_000);
  return ist.toISOString().slice(0, 10);
}

export default function App() {
  const [bot, setBot] = useState<BotStatus | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [selectedDate, setSelectedDate] = useState<string>(todayISTISO());
  const [reloadTick, setReloadTick] = useState(0);
  const loc = useLocation();
  const toast = useToast();

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const s = await api.botStatus();
        if (!alive) return;
        setBot(s);
      } catch {
        // keep last state on transient failures
      } finally {
        if (alive) timer = window.setTimeout(tick, BOT_POLL_MS);
      }
    };
    tick();
    return () => {
      alive = false;
      if (timer) window.clearTimeout(timer);
    };
  }, []);

  const item = MENU.find((m) => m.to === loc.pathname);
  const title = useMemo(() => {
    if (loc.pathname === "/overview") return "Dashboard / Overview";
    return item?.label ?? "Short Cover Cascade Bot";
  }, [item, loc.pathname]);

  const subtitle = useMemo(() => {
    if (loc.pathname === "/overview") return "Real-time view of bot state and today's activity";
    return "Auto-Reload: ON · polls every 15s";
  }, [loc.pathname]);

  const notificationCount = overview?.recent_alerts.filter((a) => a.status === "ALERT").length ?? 0;

  const onReload = useCallback(() => {
    setReloadTick((x) => x + 1);
    toast.push("Config auto-reloads on the bot's next scan", "info");
  }, [toast]);

  return (
    <div className="min-h-screen bg-bg">
      <Sidebar bot={bot} />
      <div className="ml-64">
        <Header
          title={title}
          subtitle={subtitle}
          lastSynced={overview?.last_synced_ist ?? null}
          lastConfigReload={overview?.bot.last_config_reload_ist ?? bot?.last_config_reload_ist ?? null}
          notificationCount={notificationCount}
          selectedDate={selectedDate}
          onSelectDate={setSelectedDate}
          onReload={onReload}
        />
        <main className="p-6">
          <Routes>
            <Route path="/" element={<Navigate to="/overview" replace />} />
            <Route
              path="/overview"
              element={
                <OverviewPage
                  selectedDate={selectedDate}
                  reloadTick={reloadTick}
                  onData={(d) => {
                    setOverview(d);
                    setBot(d.bot);
                  }}
                />
              }
            />
            <Route path="/configuration" element={<ConfigurationPage />} />
            <Route path="/trades-performance" element={<TradesPerformancePage />} />
            <Route path="/paper-trading" element={<PaperTradingPage />} />
            <Route path="/dashboard-reports" element={<DashboardReportsPage />} />
            {MENU.filter(
              (m) =>
                m.to !== "/overview" &&
                m.to !== "/configuration" &&
                m.to !== "/trades-performance" &&
                m.to !== "/paper-trading" &&
                m.to !== "/dashboard-reports",
            ).map((m) => (
              <Route key={m.to} path={m.to} element={<ComingSoon />} />
            ))}
            <Route path="*" element={<ComingSoon />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
