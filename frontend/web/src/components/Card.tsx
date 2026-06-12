import type { ReactNode } from "react";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border border-line bg-card p-4 shadow-card ${className}`}>
      {children}
    </div>
  );
}

export function CardTitle({
  children,
  right,
}: {
  children: ReactNode;
  right?: ReactNode;
}) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <h3 className="text-sm font-semibold text-ink">{children}</h3>
      {right ? <div className="text-xs text-muted">{right}</div> : null}
    </div>
  );
}

export function StatTile({
  label,
  value,
  tone = "neutral",
  sub,
  icon,
}: {
  label: string;
  value: ReactNode;
  tone?: "neutral" | "ok" | "warn" | "bad" | "off";
  sub?: ReactNode;
  icon?: ReactNode;
}) {
  const toneCls = {
    neutral: "text-ink",
    ok: "text-emerald-600 dark:text-emerald-400",
    warn: "text-amber-600 dark:text-amber-400",
    bad: "text-rose-600 dark:text-rose-400",
    off: "text-slate-400",
  }[tone];
  return (
    <Card>
      <div className="flex items-start justify-between">
        <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
        {icon ? <div className="text-muted">{icon}</div> : null}
      </div>
      <div className={`mt-2 text-xl font-semibold ${toneCls}`}>{value}</div>
      {sub && <div className="mt-1 text-xs text-muted">{sub}</div>}
    </Card>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-line2 ${className}`} />;
}
