import {
  Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip,
  XAxis, YAxis, Cell,
} from "recharts";
import { inr } from "../../lib/format";
import type { CumulativePoint, PnlDay } from "../../lib/api";

type Props = {
  days: PnlDay[];
  cumulative: CumulativePoint[];
  height?: number;
};

export default function PnLChart({ days, cumulative, height = 260 }: Props) {
  // Merge by date — recharts handles one composed series cleanly when the
  // data shape carries both bar + line points per row.
  const cumByDate = new Map(cumulative.map((c) => [c.date, c.net]));
  const data = days.map((d) => ({
    date: d.date.slice(5), // MM-DD for axis
    realized_pnl: d.realized_pnl,
    is_profit: d.is_profit,
    cumulative_net: cumByDate.get(d.date) ?? 0,
  }));

  if (data.length === 0) {
    return (
      <div className="flex h-[200px] items-center justify-center text-sm text-muted">
        No paper-trade P&L in this window.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 10, right: 20, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="var(--c-line2)" vertical={false} />
        <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="var(--c-muted)" />
        <YAxis
          tick={{ fontSize: 11 }}
          stroke="var(--c-muted)"
          tickFormatter={(v) => (Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(0)}k` : `${v}`)}
        />
        <Tooltip
          formatter={(v: number, key) => {
            if (key === "realized_pnl") return [inr(v), "Realized P&L"];
            if (key === "cumulative_net") return [inr(v), "Cumulative net"];
            return [v, key];
          }}
        />
        <Bar dataKey="realized_pnl" radius={[4, 4, 0, 0]} maxBarSize={28}>
          {data.map((d, i) => (
            <Cell key={i} fill={d.realized_pnl >= 0 ? "#16A34A" : "#DC2626"} />
          ))}
        </Bar>
        <Line
          type="monotone"
          dataKey="cumulative_net"
          stroke="#2563EB"
          strokeWidth={2}
          dot={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
