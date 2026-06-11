export default function ProgressBar({
  pct,
  tone = "ok",
}: {
  pct: number;
  tone?: "ok" | "warn" | "bad";
}) {
  const color = tone === "bad" ? "bg-rose-500" : tone === "warn" ? "bg-amber-500" : "bg-emerald-500";
  const clamped = Math.max(0, Math.min(100, pct));
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200">
      <div className={`${color} h-full transition-all`} style={{ width: `${clamped}%` }} />
    </div>
  );
}
