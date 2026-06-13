import { useState } from "react";
import { ConfigProvider, useConfig } from "../context/ConfigContext";
import { FeedsSection } from "../components/config/sections/FeedsSection";
import { ModeSection } from "../components/config/sections/ModeSection";
import { InstrumentsSection } from "../components/config/sections/InstrumentsSection";
import { StrikeScanningSection } from "../components/config/sections/StrikeScanningSection";
import { StopLossSection } from "../components/config/sections/StopLossSection";
import { RiskMoneySection } from "../components/config/sections/RiskMoneySection";
import { Skeleton } from "../components/Card";

type Tab = "feeds" | "mode" | "instruments" | "strikes" | "stop-loss" | "risk-money" | "more";

const TABS: { id: Tab; label: string; live: boolean }[] = [
  { id: "feeds",      label: "Feeds",             live: true  },
  { id: "mode",       label: "Mode",              live: true  },
  { id: "instruments", label: "Instruments",      live: true  },
  { id: "strikes",    label: "Strikes & Scanning", live: true  },
  { id: "stop-loss",  label: "Stop Loss",         live: true  },
  { id: "risk-money", label: "Risk & Money",      live: true  },
  { id: "more",       label: "More ▾",            live: false },
];

function ConfigLoadingState() {
  return (
    <div className="space-y-3">
      <Skeleton className="h-10 w-full" />
      <div className="rounded-xl border border-line bg-card p-5 shadow-card">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="mt-2 h-3 w-64" />
        <Skeleton className="mt-6 h-12 w-full" />
        <Skeleton className="mt-3 h-12 w-full" />
        <Skeleton className="mt-3 h-12 w-full" />
      </div>
    </div>
  );
}

function ConfigErrorState({ message }: { message: string }) {
  return (
    <div className="rounded-md border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:bg-rose-950/40 dark:text-rose-200">
      Failed to load configuration: {message}
    </div>
  );
}

function ConfigInner() {
  const { loading, error } = useConfig();
  const [tab, setTab] = useState<Tab>("feeds");

  if (loading) return <ConfigLoadingState />;
  if (error) return <ConfigErrorState message={error} />;

  return (
    <div className="space-y-4">
      {/* Tab bar */}
      <div className="flex flex-wrap gap-1 rounded-xl border border-line bg-card p-1.5 shadow-card">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => t.live && setTab(t.id)}
            disabled={!t.live}
            title={t.live ? undefined : "Coming in a later phase"}
            className={[
              "rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors",
              !t.live
                ? "cursor-not-allowed text-muted opacity-50"
                : "cursor-pointer",
              tab === t.id && t.live
                ? "bg-ink text-bg"
                : t.live
                ? "text-muted hover:text-ink"
                : "",
            ].join(" ")}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "feeds"       && <FeedsSection />}
      {tab === "mode"        && <ModeSection />}
      {tab === "instruments" && <InstrumentsSection />}
      {tab === "strikes"     && <StrikeScanningSection />}
      {tab === "stop-loss"   && <StopLossSection />}
      {tab === "risk-money"  && <RiskMoneySection />}
    </div>
  );
}

export default function ConfigurationPage() {
  return (
    <ConfigProvider>
      <ConfigInner />
    </ConfigProvider>
  );
}
