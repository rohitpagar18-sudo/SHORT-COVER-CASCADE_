import { ConfigProvider, useConfig } from "../context/ConfigContext";
import { InstrumentsSection } from "../components/config/sections/InstrumentsSection";
import { Skeleton } from "../components/Card";

function InstrumentsInner() {
  const { loading, error } = useConfig();

  if (loading) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="mt-2 h-3 w-72" />
        <Skeleton className="mt-6 h-10 w-full" />
        <Skeleton className="mt-3 h-10 w-full" />
        <Skeleton className="mt-3 h-10 w-full" />
        <Skeleton className="mt-3 h-10 w-full" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-md border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
        Failed to load configuration: {error}
      </div>
    );
  }

  return <InstrumentsSection />;
}

export default function InstrumentsPage() {
  return (
    <ConfigProvider>
      <InstrumentsInner />
    </ConfigProvider>
  );
}
