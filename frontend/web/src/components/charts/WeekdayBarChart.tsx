import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { inr } from "../../lib/format";
import type { ReportWeekday } from "../../lib/api";

type Props = {
  data: ReportWeekday[];
};

export default function WeekdayBarChart({ data }: Props) {
  if (!data || data.length === 0) {
    return (
      <div className="flex h-[180px] items-center justify-center text-sm text-muted">
        No data for this period.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="var(--c-line2)" vertical={false} />
        <XAxis
          dataKey="weekday"
          tick={{ fontSize: 11 }}
          stroke="var(--c-muted)"
        />
        <YAxis
          tick={{ fontSize: 11 }}
          stroke="var(--c-muted)"
          tickFormatter={(v) =>
            Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(0)}k` : `${v}`
          }
        />
        <Tooltip
          formatter={(v: number) => [inr(v), "P&L"]}
          labelFormatter={(label) => `Day: ${label}`}
        />
        <Bar dataKey="pnl" radius={[4, 4, 0, 0]} maxBarSize={32}>
          {data.map((d, i) => (
            <Cell key={i} fill={d.pnl >= 0 ? "#16A34A" : "#DC2626"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
