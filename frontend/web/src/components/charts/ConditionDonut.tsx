import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import type { ConditionBucket } from "../../lib/api";

type Props = {
  totalScans: number;
  buckets: ConditionBucket[];
  height?: number;
};

// Colors map highest-pass-count -> green, fading to red.
const PALETTE = ["#16A34A", "#65A30D", "#EAB308", "#F97316", "#DC2626", "#7F1D1D"];

export default function ConditionDonut({ totalScans, buckets, height = 220 }: Props) {
  const data = buckets
    .filter((b) => b.count > 0)
    .map((b, i) => ({ name: b.label, value: b.count, pct: b.pct, color: PALETTE[i % PALETTE.length] }));

  if (totalScans === 0 || data.length === 0) {
    return (
      <div className="flex h-[200px] items-center justify-center text-sm text-muted">
        No scans recorded for this date.
      </div>
    );
  }

  return (
    <div className="relative">
      <ResponsiveContainer width="100%" height={height}>
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius={62}
            outerRadius={90}
            paddingAngle={2}
            dataKey="value"
            stroke="var(--c-card)"
            strokeWidth={2}
          >
            {data.map((d, i) => (
              <Cell key={i} fill={d.color} />
            ))}
          </Pie>
          <Tooltip formatter={(v: number, _n, p: any) => [`${v} (${p.payload.pct}%)`, p.payload.name]} />
        </PieChart>
      </ResponsiveContainer>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        <div className="text-2xl font-semibold text-ink">{totalScans}</div>
        <div className="text-[11px] uppercase tracking-wide text-muted">Total scans</div>
      </div>
      <ul className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
        {buckets.map((b, i) => (
          <li key={b.label} className="flex items-center gap-1.5 text-muted">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ background: PALETTE[i % PALETTE.length] }}
            />
            <span className="text-ink">{b.label}</span>
            <span>· {b.count} ({b.pct}%)</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
