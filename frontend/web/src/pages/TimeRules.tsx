import { ConfigProvider, useConfig } from "../context/ConfigContext";
import { TimeRulesSection } from "../components/config/sections/TimeRulesSection";
import { Skeleton } from "../components/Card";

function Inner() {
  const { loading, error } = useConfig();
  if (loading) {
    return (
      <div className="rounded-xl border border-line bg-card p-5 shadow-card">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="mt-2 h-3 w-64" />
        <Skeleton className="mt-6 h-12 w-full" />
        <Skeleton className="mt-3 h-12 w-full" />
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-md border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:bg-rose-950/40 dark:text-rose-200">
        Failed to load configuration: {error}
      </div>
    );
  }
  return <TimeRulesSection />;
}

export default function TimeRulesPage() {
  return (
    <ConfigProvider>
      <Inner />
    </ConfigProvider>
  );
}
