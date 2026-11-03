import { Info } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { listPlans, type Plan } from '../api/plans'
import { listApiPrices, type ApiPrice } from '../api/prices'
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
import { formatTime, formatTokenPrice } from '../lib/utils'

export default function CostsPage() {
  const [provider, setProvider] = useState('')
  const [plans, setPlans] = useState<Plan[]>([])
  const [prices, setPrices] = useState<ApiPrice[]>([])
  const [loadingPlans, setLoadingPlans] = useState(true)
  const [loadingPrices, setLoadingPrices] = useState(true)

  const loadPlans = useCallback(async (p?: string) => {
    setLoadingPlans(true)
    try {
      const res = await listPlans(p)
      setPlans(res.items)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '套餐加载失败')
    } finally {
      setLoadingPlans(false)
    }
  }, [])

  const loadPrices = useCallback(async (p?: string) => {
    setLoadingPrices(true)
    try {
      const res = await listApiPrices(p)
      setPrices(res.items)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'API 价格加载失败')
    } finally {
      setLoadingPrices(false)
    }
  }, [])

  useEffect(() => {
    void loadPlans()
    void loadPrices()
  }, [loadPlans, loadPrices])

  const onSearch = (e: React.FormEvent) => {
    e.preventDefault()
    const p = provider.trim() || undefined
    void loadPlans(p)
    void loadPrices(p)
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>成本对比</CardTitle>
          <CardDescription>订阅套餐与 API 按量价格目录（自部署 TCO 待 M09 接入）</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-start gap-2 rounded-md border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800">
            <Info className="mt-0.5 h-4 w-4 shrink-0" />
            <span>订阅套餐为固定月费；API 按量价格按每 1M tokens 展示，便于横向对比。</span>
          </div>

          <form className="flex gap-2" onSubmit={onSearch}>
            <Input
              className="max-w-xs"
              placeholder="按 provider 筛选，如 openrouter"
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
            />
            <Button type="submit" variant="outline">
              查询
            </Button>
          </form>

          {/* API 按量价格 */}
          <div>
            <h3 className="mb-2 text-sm font-semibold">API 按量价格</h3>
            {loadingPrices ? (
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
                    <TableHead>模型</TableHead>
                    <TableHead>输入价 / 1M tokens</TableHead>
                    <TableHead>输出价 / 1M tokens</TableHead>
                    <TableHead>更新时间</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {prices.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={5} className="text-center text-muted-foreground">
                        暂无 API 价格数据，可在「采集任务」页触发 api_price 采集
                      </TableCell>
                    </TableRow>
                  ) : (
                    prices.map((p) => (
                      <TableRow key={p.id}>
                        <TableCell>{p.provider}</TableCell>
                        <TableCell className="font-mono text-xs">{p.model_id}</TableCell>
                        <TableCell>{formatTokenPrice(p.input_price)}</TableCell>
                        <TableCell>{formatTokenPrice(p.output_price)}</TableCell>
                        <TableCell>{formatTime(p.updated_at)}</TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            )}
          </div>

          {/* 订阅套餐 */}
          <div>
            <h3 className="mb-2 text-sm font-semibold">订阅套餐</h3>
            {loadingPlans ? (
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
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
