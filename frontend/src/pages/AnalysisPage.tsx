import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { Controller, useForm } from 'react-hook-form'
import {
  analysisFormSchema,
  runAnalysis,
  toRunBody,
  type AnalysisFormValues,
  type RankedModel,
} from '../api/analysis'
import { ApiError } from '../api/client'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { Input } from '../components/ui/input'
import { Label } from '../components/ui/label'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table'
import { formatCost } from '../lib/utils'

export default function AnalysisPage() {
  const [items, setItems] = useState<RankedModel[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const form = useForm<AnalysisFormValues>({
    resolver: zodResolver(analysisFormSchema),
    defaultValues: {
      benchmark_weight: 0.6,
      tokens_per_month: 1_000_000,
      input_ratio: 0.7,
    },
  })
  const benchmarkWeight = form.watch('benchmark_weight')

  const onSubmit = form.handleSubmit(async (values) => {
    setLoading(true)
    setError(null)
    try {
      const res = await runAnalysis(toRunBody(values))
      setItems(res.items)
      if (res.total === 0) setError('暂无榜单数据，请先到「采集任务」页触发采集')
    } catch (e) {
      setItems(null)
      setError(
        e instanceof ApiError
          ? e.message
          : e instanceof Error
            ? e.message
            : '分析请求失败',
      )
    } finally {
      setLoading(false)
    }
  })

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>智能分析引擎</CardTitle>
          <p className="text-sm text-muted-foreground">
            根据你的权重偏好与用量假设，对候选模型加权打分并给出推荐排名
          </p>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={(e) => void onSubmit(e)}
            className="flex flex-wrap items-end gap-4"
          >
            <div className="w-64 space-y-1.5">
              <Label htmlFor="benchmark_weight">
                榜单权重 {(benchmarkWeight * 100).toFixed(0)}% / 价格权重{' '}
                {((1 - benchmarkWeight) * 100).toFixed(0)}%
              </Label>
              <Controller
                control={form.control}
                name="benchmark_weight"
                render={({ field }) => (
                  <input
                    id="benchmark_weight"
                    type="range"
                    min={0}
                    max={1}
                    step={0.05}
                    className="w-full accent-primary"
                    value={field.value}
                    onChange={(e) => field.onChange(Number(e.target.value))}
                  />
                )}
              />
            </div>

            <div className="w-44 space-y-1.5">
              <Label htmlFor="tokens_per_month">月用量（tokens）</Label>
              <Input
                id="tokens_per_month"
                type="number"
                min={1}
                step={1}
                {...form.register('tokens_per_month', { valueAsNumber: true })}
              />
              {form.formState.errors.tokens_per_month && (
                <p className="text-xs text-red-600">
                  {form.formState.errors.tokens_per_month.message}
                </p>
              )}
            </div>

            <div className="w-48 space-y-1.5">
              <Label htmlFor="input_ratio">
                输入 token 占比 {(form.watch('input_ratio') * 100).toFixed(0)}%
              </Label>
              <Controller
                control={form.control}
                name="input_ratio"
                render={({ field }) => (
                  <input
                    id="input_ratio"
                    type="range"
                    min={0}
                    max={1}
                    step={0.05}
                    className="w-full accent-primary"
                    value={field.value}
                    onChange={(e) => field.onChange(Number(e.target.value))}
                  />
                )}
              />
            </div>

            <Button type="submit" disabled={loading}>
              {loading ? '分析中…' : '开始分析'}
            </Button>
          </form>
          {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
        </CardContent>
      </Card>

      {items && items.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>推荐排名</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-16">排名</TableHead>
                  <TableHead>模型</TableHead>
                  <TableHead>厂商</TableHead>
                  <TableHead>综合分</TableHead>
                  <TableHead>榜单分</TableHead>
                  <TableHead>价格分</TableHead>
                  <TableHead>预估月成本</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((item) => (
                  <TableRow key={item.model_id}>
                    <TableCell>{item.rank}</TableCell>
                    <TableCell className="font-medium">
                      {item.display_name ?? item.model_id}
                    </TableCell>
                    <TableCell>{item.provider}</TableCell>
                    <TableCell>{item.composite_score.toFixed(3)}</TableCell>
                    <TableCell>{item.benchmark_norm.toFixed(3)}</TableCell>
                    <TableCell>{item.price_norm.toFixed(3)}</TableCell>
                    <TableCell>{formatCost(item.monthly_cost)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
