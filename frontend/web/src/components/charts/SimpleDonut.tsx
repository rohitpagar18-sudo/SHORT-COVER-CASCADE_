import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

type DonutItem = {
  name: string;
  value: number;
  pct: number;
  color: string;
};

type Props = {
  items: DonutItem[];
};

export default function SimpleDonut({ items }: Props) {
  if (!items || items.length === 0) {
    return (
      <div className="flex h-[180px] items-center justify-center text-sm text-muted">
        No data for this period.
      </div>
    );
  }

  const total = items.reduce((acc, it) => acc + it.value, 0);

  return (
    <div className="flex flex-col items-center gap-3">
      <div className="relative">
        <ResponsiveContainer width={160} height={160}>
          <PieChart>
            <Pie
              data={items}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="50%"
              innerRadius={50}
              outerRadius={72}
              strokeWidth={0}
            >
              {items.map((item, i) => (
                <Cell key={i} fill={item.color} />
              ))}
            </Pie>
            <Tooltip
              formatter={(v: number, name: string) => {
                const item = items.find((it) => it.name === name);
                return [`${v} (${item?.pct ?? 0}%)`, name];
              }}
            />
          </PieChart>
        </ResponsiveContainer>
        {/* Center label */}
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <div className="text-center">
            <div className="text-lg font-bold text-ink">{total}</div>
            <div className="text-[10px] text-muted">total</div>
          </div>
        </div>
      </div>

      {/* Legend */}
      <ul className="w-full space-y-1">
        {items.map((item) => (
          <li key={item.name} className="flex items-center justify-between gap-2 text-xs">
            <span className="flex items-center gap-1.5">
              <span
                className="inline-block h-2.5 w-2.5 flex-shrink-0 rounded-full"
                style={{ backgroundColor: item.color }}
              />
              <span className="text-ink">{item.name}</span>
            </span>
            <span className="text-muted">
              {item.value} ({item.pct}%)
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
