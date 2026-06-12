import { Line, LineChart, ResponsiveContainer, Tooltip, YAxis } from "recharts";

type Props = { data: Array<{ t: string; price: number }>; height?: number };

export default function PriceSparkline({ data, height = 80 }: Props) {
  if (data.length === 0) {
    return (
      <div className="flex h-[80px] items-center justify-center text-xs text-muted">
        Live price stream not available
      </div>
    );
  }
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data}>
        <YAxis hide domain={["auto", "auto"]} />
        <Tooltip formatter={(v: number) => [v, "Price"]} />
        <Line type="monotone" dataKey="price" stroke="#2563EB" strokeWidth={2} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}
