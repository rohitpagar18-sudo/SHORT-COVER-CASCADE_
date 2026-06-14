import { Line, LineChart, ResponsiveContainer } from "recharts";

type Props = {
  data: number[];
  positive?: boolean;
};

export default function KpiSparkline({ data, positive = true }: Props) {
  if (!data || data.length < 2) {
    return null;
  }

  const chartData = data.map((v, i) => ({ i, v }));
  const strokeColor = positive ? "#16A34A" : "#DC2626";

  return (
    <ResponsiveContainer width={80} height={32}>
      <LineChart data={chartData} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
        <Line
          type="monotone"
          dataKey="v"
          stroke={strokeColor}
          strokeWidth={1.5}
          dot={false}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
