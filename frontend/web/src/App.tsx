import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import Sidebar, { MENU } from "./components/Sidebar";
import Header from "./components/Header";
import ComingSoon from "./components/ComingSoon";
import OverviewPage from "./pages/Overview";
import ConfigurationPage from "./pages/Configuration";
import InstrumentsPage from "./pages/Instruments";
import { api, type BotStatus, type Overview } from "./lib/api";

const BOT_POLL_MS = 15_000;

export default function App() {
  const [bot, setBot] = useState<BotStatus | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const loc = useLocation();

  // Poll bot status independently of the Overview page so the sidebar
  // pill stays live on every route.
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
  const title = item?.label ?? "Short Cover Cascade Bot";

  return (
    <div className="min-h-screen">
      <Sidebar bot={bot} />
      <div className="ml-64">
        <Header title={title} lastSynced={overview?.last_synced_ist ?? null} />
        <main className="p-6">
          <Routes>
            <Route path="/" element={<Navigate to="/overview" replace />} />
            <Route
              path="/overview"
              element={<OverviewPage onData={(d) => { setOverview(d); setBot(d.bot); }} />}
            />
            <Route path="/configuration" element={<ConfigurationPage />} />
            <Route path="/instruments" element={<InstrumentsPage />} />
            {MENU.filter(
              (m) =>
                m.to !== "/overview" &&
                m.to !== "/configuration" &&
                m.to !== "/instruments",
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
