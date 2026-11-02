import { Info } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { listPlans, type Plan } from '../api/plans'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Input } from '../components/ui/input'
import { Skeleton } from '../components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table'
import { formatTime } from '../lib/utils'

export default function CostsPage() {
  const [provider, setProvider] = useState('')
  const [plans, setPlans] = useState<Plan[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async (p?: string) => {
    setLoading(true)
    try {
      const res = await listPlans(p)
      setPlans(res.items)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '套餐加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <Card>
      <CardHeader>
        <CardTitle>成本对比</CardTitle>
        <CardDescription>订阅套餐目录（API 价格与自部署 TCO 见下方说明）</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-start gap-2 rounded-md border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800">
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
          <span>M09 TCO 就绪后接入「订阅 / API 按量 / 自部署」三方案对比，本期仅展示订阅套餐目录。</span>
        </div>

        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            void load(provider.trim() || undefined)
          }}
        >
          <Input
            className="max-w-xs"
            placeholder="按 provider 筛选，如 openai"
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
          />
          <Button type="submit" variant="outline">
            查询
          </Button>
        </form>

        {loading ? (
          <div className="space-y-2">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>厂商</TableHead>
                <TableHead>套餐</TableHead>
                <TableHead>月价</TableHead>
                <TableHead>计费周期</TableHead>
                <TableHead>更新时间</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {plans.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-muted-foreground">
                    暂无套餐数据
                  </TableCell>
                </TableRow>
              ) : (
                plans.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell>{p.provider}</TableCell>
                    <TableCell>{p.plan_name}</TableCell>
                    <TableCell>
                      {p.monthly_price} {p.currency}
                    </TableCell>
                    <TableCell>{p.billing_cycle === 'yearly' ? '年付' : '月付'}</TableCell>
                    <TableCell>{formatTime(p.updated_at)}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}
