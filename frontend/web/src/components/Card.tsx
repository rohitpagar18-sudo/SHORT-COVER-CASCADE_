import type { ReactNode } from "react";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border border-slate-200 bg-white p-4 shadow-sm ${className}`}>
      {children}
    </div>
  );
}

export function CardTitle({ children }: { children: ReactNode }) {
  return <h3 className="mb-3 text-sm font-semibold text-ink">{children}</h3>;
}

export function StatTile({
  label,
  value,
  tone = "neutral",
  sub,
}: {
  label: string;
  value: ReactNode;
  tone?: "neutral" | "ok" | "warn" | "bad" | "off";
  sub?: ReactNode;
}) {
  const toneCls = {
    neutral: "text-ink",
    ok: "text-emerald-600",
    warn: "text-amber-600",
    bad: "text-rose-600",
    off: "text-slate-400",
  }[tone];
  return (
    <Card>
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className={`mt-1 text-xl font-semibold ${toneCls}`}>{value}</div>
      {sub && <div className="mt-1 text-xs text-muted">{sub}</div>}
    </Card>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-slate-200/70 ${className}`} />;
}
