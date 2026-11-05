import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { listModels } from '../api/models'
import { CompareRadarChart, type RadarRow } from '../components/Chart'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Input } from '../components/ui/input'
import { Skeleton } from '../components/ui/skeleton'

/** 对比维度（与榜单列一致） */
const DIMENSIONS = ['intelligence', 'coding', 'agentic', 'long_context', 'image', 'video']

const DIMENSION_LABELS: Record<string, string> = {
  intelligence: '智力',
  coding: '编程',
  agentic: '智能体',
  long_context: '长上下文',
  image: '图像生成',
  video: '视频生成',
}

const MAX_SELECTED = 6

interface CompareEntry {
  model_id: string
  provider: string
  scores: Record<string, number | null>
  benchmark: number | null
}

export default function ComparePage() {
  const [entries, setEntries] = useState<CompareEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<string[]>([])
  const [keyword, setKeyword] = useState('')

  useEffect(() => {
    listModels(1, 100)
      .then((res) => {
        setEntries(
          res.items
            .map((s) => ({
              model_id: s.model_id,
              provider: s.provider,
              scores: s.scores ?? {},
              benchmark: s.benchmark_score === null ? null : Number(s.benchmark_score),
            }))
            .sort((a, b) => (b.benchmark ?? -1) - (a.benchmark ?? -1)),
        )
      })
      .catch((e: unknown) => toast.error(e instanceof Error ? e.message : '数据加载失败'))
      .finally(() => setLoading(false))
  }, [])

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    if (!kw) return entries
    return entries.filter(
      (e) => e.model_id.toLowerCase().includes(kw) || e.provider.toLowerCase().includes(kw),
    )
  }, [entries, keyword])

  const toggle = (modelId: string) => {
    setSelected((prev) => {
      if (prev.includes(modelId)) return prev.filter((m) => m !== modelId)
      if (prev.length >= MAX_SELECTED) {
        toast.warning(`最多同时对比 ${MAX_SELECTED} 个模型`)
        return prev
      }
      return [...prev, modelId]
    })
  }

  const radarData: RadarRow[] = DIMENSIONS.map((dim) => {
    const row: RadarRow = { dimension: DIMENSION_LABELS[dim] ?? dim }
    for (const modelId of selected) {
      const entry = entries.find((e) => e.model_id === modelId)
      const value = entry?.scores?.[dim]
      // 缺失维度按 0 展示（雷达图不支持 null），hover 明细仍可看原始分
      row[modelId] = value ?? 0
    }
    return row
  })

  return (
    <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
      <Card>
        <CardHeader>
          <CardTitle>选择模型</CardTitle>
          <CardDescription>勾选 2-{MAX_SELECTED} 个模型进行多维对比</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Input
            placeholder="搜索模型或厂商…"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
          />
          {loading ? (
            <div className="space-y-2">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </div>
          ) : (
            <ul className="max-h-[480px] space-y-1 overflow-auto pr-1">
              {filtered.map((e) => (
                <li key={e.model_id}>
                  <label className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-primary"
                      checked={selected.includes(e.model_id)}
                      onChange={() => toggle(e.model_id)}
                    />
                    <span className="flex-1 break-all">{e.model_id}</span>
                    <span className="text-xs text-muted-foreground">
                      {e.benchmark === null ? '-' : e.benchmark.toFixed(2)}
                    </span>
                  </label>
                </li>
              ))}
              {filtered.length === 0 && (
                <li className="py-4 text-center text-sm text-muted-foreground">无匹配模型</li>
              )}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>多维对比</CardTitle>
          <CardDescription>
            {selected.length > 0
              ? `已选 ${selected.length} 个模型：${selected.join('、')}`
              : '按 智力 / 编程 / 智能体 / 长上下文 / 图像 / 视频 维度对比'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {selected.length === 0 ? (
            <p className="py-16 text-center text-sm text-muted-foreground">
              请先从左侧勾选要对比的模型
            </p>
          ) : (
            <CompareRadarChart data={radarData} models={selected} />
          )}
        </CardContent>
      </Card>
    </div>
  )
}
