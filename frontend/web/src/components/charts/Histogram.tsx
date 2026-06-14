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

type HistogramItem = { bucket?: string; r_bucket?: string; risk_bucket?: string; count: number; color?: string };

type Props = {
  data: HistogramItem[];
  xLabel?: string;
  yLabel?: string;
  height?: number;
};

export default function Histogram({ data, xLabel = "Bucket", yLabel = "Count", height = 180 }: Props) {
  if (!data || data.length === 0) {
    return (
      <div className="flex h-[180px] items-center justify-center text-sm text-muted">
        No data for this period.
      </div>
    );
  }

  const colors = ["#3B82F6", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6", "#EC4899"];

  // Normalize to a common 'label' key for recharts
  const normalizedData = data.map((item) => ({
    label: item.bucket || item.r_bucket || item.risk_bucket || "—",
    count: item.count,
    color: item.color,
  }));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={normalizedData} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
        <CartesianGrid stroke="var(--c-line2)" vertical={false} />
        <XAxis dataKey="label" tick={{ fontSize: 11 }} stroke="var(--c-muted)" />
        <YAxis tick={{ fontSize: 11 }} stroke="var(--c-muted)" />
        <Tooltip formatter={(v: number) => [v.toLocaleString(), yLabel]} />
        <Bar dataKey="count" radius={[4, 4, 0, 0]} maxBarSize={40}>
          {normalizedData.map((item, i) => (
            <Cell key={i} fill={item.color || colors[i % colors.length]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
