import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { listModels } from '../api/models'
import { DOMAIN_LABELS } from '../api/tasks'
import { CompareRadarChart, type RadarRow } from '../components/Chart'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Input } from '../components/ui/input'
import { Skeleton } from '../components/ui/skeleton'

const DOMAIN_KEYS = ['general', 'chat', 'coding']
const MAX_SELECTED = 6

interface CompareEntry {
  model_id: string
  provider: string
  scores: Record<string, number>
}

export default function ComparePage() {
  const [entries, setEntries] = useState<CompareEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<string[]>([])
  const [keyword, setKeyword] = useState('')

  useEffect(() => {
    // 拉取三个 domain 的榜单，按 model_id 合并出「模型 × domain 分数」矩阵
    Promise.all(DOMAIN_KEYS.map((d) => listModels(d)))
      .then((results) => {
        const map = new Map<string, CompareEntry>()
        results.forEach((res, i) => {
          for (const s of res.items) {
            const entry =
              map.get(s.model_id) ?? { model_id: s.model_id, provider: s.provider, scores: {} }
            entry.scores[DOMAIN_KEYS[i]] = Number(s.benchmark_score)
            map.set(s.model_id, entry)
          }
        })
        setEntries(
          [...map.values()].sort(
            (a, b) =>
              Math.max(...Object.values(b.scores), 0) - Math.max(...Object.values(a.scores), 0),
          ),
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

  const radarData: RadarRow[] = DOMAIN_KEYS.map((domain) => {
    const row: RadarRow = { domain: DOMAIN_LABELS[domain] ?? domain }
    for (const modelId of selected) {
      row[modelId] = entries.find((e) => e.model_id === modelId)?.scores[domain] ?? 0
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
                      {Math.max(...Object.values(e.scores), 0).toFixed(2)}
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
              : '按 通用 / 对话 / 代码 三个 domain 维度对比'}
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
