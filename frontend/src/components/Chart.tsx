import {
  Legend,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
} from 'recharts'

/** 图表配色（按系列顺序循环） */
const COLORS = ['#2563eb', '#16a34a', '#dc2626', '#9333ea', '#ea580c', '#0891b2']

export interface RadarRow {
  dimension: string
  [model: string]: string | number
}

/** 模型对比雷达图：dimension 为能力维度，每个选中模型一条雷达线 */
export function CompareRadarChart({ data, models }: { data: RadarRow[]; models: string[] }) {
  return (
    <ResponsiveContainer width="100%" height={360}>
      <RadarChart data={data} cx="50%" cy="50%" outerRadius="75%">
        <PolarGrid />
        <PolarAngleAxis dataKey="dimension" fontSize={12} />
        <PolarRadiusAxis fontSize={10} />
        <Tooltip />
        <Legend />
        {models.map((model, i) => (
          <Radar
            key={model}
            name={model}
            dataKey={model}
            stroke={COLORS[i % COLORS.length]}
            fill={COLORS[i % COLORS.length]}
            fillOpacity={0.15}
          />
        ))}
      </RadarChart>
    </ResponsiveContainer>
  )
}
