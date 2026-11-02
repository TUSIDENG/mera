import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

/** 图表配色（按系列顺序循环） */
const COLORS = ['#2563eb', '#16a34a', '#dc2626', '#9333ea', '#ea580c', '#0891b2']

export interface HistoryPoint {
  time: string
  [domain: string]: string | number
}

/** 模型历史快照折线图：x 轴为更新时间，按 domain 分线 */
export function HistoryLineChart({ data, domains }: { data: HistoryPoint[]; domains: string[] }) {
  return (
    <ResponsiveContainer width="100%" height={320}>
      <LineChart data={data} margin={{ top: 8, right: 24, bottom: 8, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="time" fontSize={12} />
        <YAxis fontSize={12} domain={['auto', 'auto']} />
        <Tooltip />
        <Legend />
        {domains.map((domain, i) => (
          <Line
            key={domain}
            type="monotone"
            dataKey={domain}
            stroke={COLORS[i % COLORS.length]}
            dot={{ r: 2 }}
            connectNulls
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}

export interface RadarRow {
  domain: string
  [model: string]: string | number
}

/** 模型对比雷达图：domain 为维度，每个选中模型一条雷达线 */
export function CompareRadarChart({ data, models }: { data: RadarRow[]; models: string[] }) {
  return (
    <ResponsiveContainer width="100%" height={360}>
      <RadarChart data={data} cx="50%" cy="50%" outerRadius="75%">
        <PolarGrid />
        <PolarAngleAxis dataKey="domain" fontSize={12} />
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
