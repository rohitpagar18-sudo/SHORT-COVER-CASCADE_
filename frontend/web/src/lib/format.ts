export function inr(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "₹0";
  const sign = n < 0 ? "-" : "";
  const v = Math.abs(n);
  return `${sign}₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

export function pct(num: number, den: number): number {
  if (!den || den <= 0) return 0;
  return Math.max(0, Math.min(100, (num / den) * 100));
}

export function timeAgoIST(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return "—";
  const sec = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

export function hhmm(iso: string | null | undefined): string {
  if (!iso) return "—";
  const m = iso.match(/T(\d{2}:\d{2})/);
  return m ? m[1] : "—";
}
