import type { PnlTotals } from "../../lib/api";
import { inr, inrSigned } from "../../lib/format";

export default function StatPanel({ totals }: { totals: PnlTotals }) {
  const items: Array<{ label: string; value: string; tone: "ok" | "bad" | "neutral" }> = [
    { label: "Total P&L", value: inrSigned(totals.total_pnl), tone: totals.total_pnl >= 0 ? "ok" : "bad" },
    { label: "Realized P&L", value: inrSigned(totals.realized_pnl), tone: totals.realized_pnl >= 0 ? "ok" : "bad" },
    { label: "Unrealized P&L", value: inrSigned(totals.unrealized_pnl), tone: "neutral" },
    { label: "Max Daily Profit", value: inr(totals.max_daily_profit), tone: "ok" },
    { label: "Max Daily Loss", value: inr(totals.max_daily_loss), tone: "bad" },
  ];
  return (
    <ul className="space-y-3 text-sm">
      {items.map((it) => (
        <li key={it.label} className="flex items-center justify-between">
          <span className="text-muted">{it.label}</span>
          <span
            className={
              it.tone === "ok"
                ? "font-semibold text-emerald-600 dark:text-emerald-400"
                : it.tone === "bad"
                ? "font-semibold text-rose-600 dark:text-rose-400"
                : "font-medium text-ink"
            }
          >
            {it.value}
          </span>
        </li>
      ))}
    </ul>
  );
}
