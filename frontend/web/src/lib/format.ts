export function inr(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "₹0";
  const sign = n < 0 ? "-" : "";
  const v = Math.abs(n);
  return `${sign}₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

export function inrSigned(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "₹0";
  const sign = n > 0 ? "+" : n < 0 ? "-" : "";
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

export function fmtClock(iso: string | null | undefined): string {
  if (!iso) return "—";
  const m = iso.match(/T(\d{2}:\d{2})/);
  return m ? m[1] : "—";
}

export function fmtUptime(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) {
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return `${h}h ${m}m`;
  }
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  return `${d}d ${h}h`;
}

export function fmtDateLong(iso: string | null | undefined): string {
  if (!iso) return "—";
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return iso;
  const months = [
    "Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec",
  ];
  return `${parseInt(m[3], 10)} ${months[parseInt(m[2], 10) - 1]} ${m[1]}`;
}
