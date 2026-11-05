import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { toast } from 'sonner'
import {
  listModelFetchRecords,
  listModelSnapshots,
  type FetchRecord,
  type LlmScore,
  type Snapshot,
  type SourceEntry,
} from '../api/models'
import { DOMAIN_LABELS } from '../api/tasks'
import { Badge } from '../components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Skeleton } from '../components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table'
import { formatScore, formatTime } from '../lib/utils'

/** 榜单固定维度（与后端 llm_scoring/prompt.py DIMENSIONS 一致） */
const DIMENSIONS = ['intelligence', 'coding', 'agentic', 'long_context', 'image', 'video']

const DIMENSION_LABELS: Record<string, string> = {
  intelligence: '智力',
  coding: '编程',
  agentic: '智能体',
  long_context: '长上下文',
  image: '图像生成',
  video: '视频生成',
}

/** 读取 snapshot.data.sources（容错非对象场景） */
function sourcesOf(snapshot: Snapshot): Record<string, SourceEntry> {
  const sources = snapshot.data?.sources
  if (!sources || typeof sources !== 'object') return {}
  return sources as Record<string, SourceEntry>
}

/** 读取 snapshot.data.llm_score（容错缺失） */
function llmScoreOf(snapshot: Snapshot): LlmScore | null {
  const llm = snapshot.data?.llm_score
  if (!llm || typeof llm !== 'object') return null
  return llm as LlmScore
}

/** 采集记录分数摘要：主榜分 + 非空维度分 */
function recordScoreSummary(record: FetchRecord): string {
  const parts: string[] = []
  const benchmark = record.record?.benchmark_score
  if (typeof benchmark === 'number') parts.push(`主榜 ${formatScore(benchmark)}`)
  const scores = record.record?.scores
  if (scores && typeof scores === 'object') {
    for (const [dim, value] of Object.entries(scores as Record<string, number | null>)) {
      if (value !== null && value !== undefined) parts.push(`${dim} ${formatScore(value)}`)
    }
  }
  return parts.length > 0 ? parts.join(' · ') : '-'
}

function JsonDetails({ label, value }: { label: string; value: unknown }) {
  return (
    <details className="text-xs">
      <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
        {label}
      </summary>
      <pre className="mt-1 max-h-72 overflow-auto rounded bg-muted p-2">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  )
}

function LlmScoreView({ llm }: { llm: LlmScore }) {
  return (
    <div className="rounded border border-blue-200 bg-blue-50 p-3 text-sm dark:border-blue-900 dark:bg-blue-950">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary">LLM 打分</Badge>
        <span className="font-medium">综合 {formatScore(llm.overall)}</span>
        <span className="text-muted-foreground">
          {Object.entries(llm.dims ?? {})
            .map(([dim, v]) => `${DIMENSION_LABELS[dim] ?? dim}: ${v === null ? '-' : formatScore(v)}`)
            .join(' / ')}
        </span>
      </div>
      {llm.rationale && <p className="mt-1 text-muted-foreground">{llm.rationale}</p>}
      <p className="mt-1 text-xs text-muted-foreground">
        打分模型 {llm.scorer} · {formatTime(llm.scored_at)}
      </p>
    </div>
  )
}

export default function ModelDetailPage() {
  const { modelId = '' } = useParams()
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [records, setRecords] = useState<FetchRecord[]>([])
  const [recordsTotal, setRecordsTotal] = useState(0)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!modelId) return
    setLoading(true)
    listModelSnapshots(modelId)
      .then((items) => setSnapshot(items[0] ?? null))
      .catch((e: unknown) =>
        toast.error(e instanceof Error ? e.message : '快照加载失败'),
      )
      .finally(() => setLoading(false))
    listModelFetchRecords(modelId)
      .then((res) => {
        setRecords(res.items)
        setRecordsTotal(res.total)
      })
      .catch((e: unknown) =>
        toast.error(e instanceof Error ? e.message : '采集历史加载失败'),
      )
  }, [modelId])

  const scores = snapshot?.scores ?? {}
  const sources = snapshot ? sourcesOf(snapshot) : {}
  const llm = snapshot ? llmScoreOf(snapshot) : null

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="break-all">{modelId}</CardTitle>
          <CardDescription>
            厂商：{snapshot?.provider ?? '-'}
            {snapshot && ` · 更新于 ${formatTime(snapshot.updated_at)}`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <Skeleton className="h-40 w-full" />
          ) : !snapshot ? (
            <p className="py-8 text-center text-sm text-muted-foreground">暂无榜单数据</p>
          ) : (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-2xl font-semibold">{formatScore(snapshot.benchmark_score)}</span>
                <span className="text-sm text-muted-foreground">主榜分</span>
                {snapshot.score_source && (
                  <Badge variant="outline">来源 {snapshot.score_source}</Badge>
                )}
              </div>
              {llm && <LlmScoreView llm={llm} />}
              <Table>
                <TableHeader>
                  <TableRow>
                    {DIMENSIONS.map((dim) => (
                      <TableHead key={dim}>{DIMENSION_LABELS[dim] ?? dim}</TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableRow>
                    {DIMENSIONS.map((dim) => {
                      const value = scores[dim]
                      return (
                        <TableCell key={dim}>
                          {value === null || value === undefined ? (
                            <span className="text-muted-foreground">-</span>
                          ) : (
                            formatScore(value)
                          )}
                        </TableCell>
                      )
                    })}
                  </TableRow>
                </TableBody>
              </Table>
              {!llm && (
                <p className="text-xs text-muted-foreground">
                  维度分为采集数据聚合结果；开启 LLM 打分后由大模型按采集数据统一评定，无法得出的维度显示 -。
                </p>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>采集详情</CardTitle>
          <CardDescription>各平台采集到的原始数据（同一模型多平台合并在一行）</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {loading ? (
            <Skeleton className="h-40 w-full" />
          ) : Object.keys(sources).length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">暂无采集数据</p>
          ) : (
            Object.entries(sources).map(([sourceKey, entry]) => (
              <div key={sourceKey} className="rounded border p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge>{sourceKey}</Badge>
                  {entry?.domain && (
                    <Badge variant="secondary">
                      {DOMAIN_LABELS[entry.domain] ?? entry.domain}
                    </Badge>
                  )}
                  <span className="text-muted-foreground">
                    原始模型名：{entry?.raw_model_id ?? '-'}
                  </span>
                </div>
                <div className="mt-2">
                  <JsonDetails label="查看采集到的原始数据" value={entry?.record} />
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>采集历史</CardTitle>
          <CardDescription>共 {recordsTotal} 条留痕（按时间倒序）</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>时间</TableHead>
                <TableHead>平台</TableHead>
                <TableHead>原始模型名</TableHead>
                <TableHead>分数摘要</TableHead>
                <TableHead>明细</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {records.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-muted-foreground">
                    暂无采集留痕
                  </TableCell>
                </TableRow>
              ) : (
                records.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell>{formatTime(r.created_at)}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{r.source_key}</Badge>
                    </TableCell>
                    <TableCell className="break-all">{r.raw_model_id ?? '-'}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {recordScoreSummary(r)}
                    </TableCell>
                    <TableCell>
                      <JsonDetails label="JSON" value={r.record} />
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
