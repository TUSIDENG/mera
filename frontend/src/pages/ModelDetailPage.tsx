import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { listModelSnapshots, type Snapshot } from '../api/models'
import { DOMAIN_LABELS } from '../api/tasks'
import { HistoryLineChart, type HistoryPoint } from '../components/Chart'
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

export default function ModelDetailPage() {
  const { modelId = '' } = useParams()
  const [snapshots, setSnapshots] = useState<Snapshot[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!modelId) return
    setLoading(true)
    listModelSnapshots(modelId)
      .then(setSnapshots)
      .catch((e: unknown) =>
        toast.error(e instanceof Error ? e.message : '快照加载失败'),
      )
      .finally(() => setLoading(false))
  }, [modelId])

  const sorted = [...snapshots].sort((a, b) => a.updated_at.localeCompare(b.updated_at))
  const domains = [...new Set(sorted.map((s) => s.domain))]
  const chartData: HistoryPoint[] = sorted.map((s) => ({
    time: formatTime(s.updated_at),
    [s.domain]: Number(s.benchmark_score),
  }))
  const provider = snapshots[0]?.provider ?? '-'

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="break-all">{modelId}</CardTitle>
          <CardDescription>
            厂商：{provider} · 共 {snapshots.length} 条历史快照
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <Skeleton className="h-72 w-full" />
          ) : snapshots.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">暂无历史快照</p>
          ) : (
            <HistoryLineChart data={chartData} domains={domains} />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>历史快照</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <Skeleton className="h-40 w-full" />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>领域</TableHead>
                  <TableHead>分数</TableHead>
                  <TableHead>更新时间</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {[...snapshots]
                  .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
                  .map((s) => (
                    <TableRow key={s.id}>
                      <TableCell>
                        <Badge variant="secondary">{DOMAIN_LABELS[s.domain] ?? s.domain}</Badge>
                      </TableCell>
                      <TableCell>{formatScore(s.benchmark_score)}</TableCell>
                      <TableCell>{formatTime(s.updated_at)}</TableCell>
                    </TableRow>
                  ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
