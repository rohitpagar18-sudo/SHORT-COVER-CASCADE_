import { useState } from "react";
import { ConfigProvider, useConfig } from "../context/ConfigContext";
import { FeedsSection } from "../components/config/sections/FeedsSection";
import { ModeSection } from "../components/config/sections/ModeSection";
import { InstrumentsSection } from "../components/config/sections/InstrumentsSection";
import { StrikeScanningSection } from "../components/config/sections/StrikeScanningSection";
import { StopLossSection } from "../components/config/sections/StopLossSection";
import { RiskMoneySection } from "../components/config/sections/RiskMoneySection";
import { ConditionsSection } from "../components/config/sections/ConditionsSection";
import { TimeRulesSection } from "../components/config/sections/TimeRulesSection";
import { ReEntrySection } from "../components/config/sections/ReEntrySection";
import { AlertsTelegramSection } from "../components/config/sections/AlertsTelegramSection";
import { OrdersSection } from "../components/config/sections/OrdersSection";
import { Skeleton } from "../components/Card";

type Tab =
  | "feeds" | "mode" | "instruments" | "strikes"
  | "stop-loss" | "risk-money" | "conditions"
  | "time-rules" | "re-entry" | "telegram" | "orders";

const TABS: { id: Tab; label: string }[] = [
  { id: "feeds",       label: "Feeds"             },
  { id: "mode",        label: "Mode"              },
  { id: "instruments", label: "Instruments"       },
  { id: "strikes",     label: "Strikes & Scanning" },
  { id: "stop-loss",   label: "Stop Loss"         },
  { id: "risk-money",  label: "Risk & Money"      },
  { id: "conditions",  label: "Conditions"        },
  { id: "time-rules",  label: "Time Rules"        },
  { id: "re-entry",    label: "Re-entry"          },
  { id: "telegram",    label: "Alerts & Telegram" },
  { id: "orders",      label: "Orders"            },
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
            onClick={() => setTab(t.id)}
            className={[
              "rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors",
              tab === t.id
                ? "bg-ink text-bg"
                : "cursor-pointer text-muted hover:text-ink",
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
      {tab === "conditions"  && <ConditionsSection />}
      {tab === "time-rules"  && <TimeRulesSection />}
      {tab === "re-entry"    && <ReEntrySection />}
      {tab === "telegram"    && <AlertsTelegramSection />}
      {tab === "orders"      && <OrdersSection />}
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
