import { zodResolver } from '@hookform/resolvers/zod'
import { useCallback, useEffect, useState } from 'react'
import { Controller, useForm } from 'react-hook-form'
import { toast } from 'sonner'
import {
  createFetchTask,
  fetchTaskFormSchema,
  listFetchTasks,
  TASK_TYPES,
  TASK_TYPE_LABELS,
  type FetchTask,
  type FetchTaskFormValues,
  type TaskType,
} from '../api/tasks'
import { listSites, type CollectionSite } from '../api/sites'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Input } from '../components/ui/input'
import { Label } from '../components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table'
import { formatTime } from '../lib/utils'

const POLL_INTERVAL_MS = 10_000

/** 任务状态徽标配色（与后端状态机取值一致） */
const STATUS_STYLES: Record<string, { label: string; className: string }> = {
  pending: { label: '排队中', className: 'bg-slate-100 text-slate-700' },
  running: { label: '运行中', className: 'bg-blue-100 text-blue-700' },
  succeeded: { label: '成功', className: 'bg-green-100 text-green-700' },
  partial_succeeded: { label: '部分成功', className: 'bg-amber-100 text-amber-700' },
  failed_exhausted: { label: '失败', className: 'bg-red-100 text-red-700' },
  captcha_pending: { label: '待验证码', className: 'bg-purple-100 text-purple-700' },
}

function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] ?? { label: status, className: 'bg-slate-100 text-slate-700' }
  return <Badge className={style.className}>{style.label}</Badge>
}

const FORM_DEFAULTS: FetchTaskFormValues = {
  task_type: 'model_metrics',
  source_key: '',
  domain: '',
  fetch_strategy: 'auto',
}

export default function TasksPage() {
  const [tasks, setTasks] = useState<FetchTask[]>([])
  const [total, setTotal] = useState(0)
  const [sites, setSites] = useState<CollectionSite[]>([])

  const form = useForm<FetchTaskFormValues>({
    resolver: zodResolver(fetchTaskFormSchema),
    defaultValues: FORM_DEFAULTS,
  })

  const load = useCallback(async () => {
    try {
      const res = await listFetchTasks()
      setTasks(res.items)
      setTotal(res.total)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '任务列表加载失败')
    }
  }, [])

  // 首次加载任务列表 + 站点列表（站点列表用于任务类型联动）
  useEffect(() => {
    void load()
    void listSites().then(setSites).catch((e) => {
      toast.error(e instanceof Error ? e.message : '站点列表加载失败')
    })
    const timer = setInterval(() => void load(), POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [load])

  // 选中站点后：domain 联动 + task_type 自动对齐到该站点支持的类型
  const sourceKey = form.watch('source_key')
  const selectedSite = sites.find((s) => s.key === sourceKey)
  useEffect(() => {
    if (!selectedSite) return
    form.setValue('domain', selectedSite.domain ?? '')
    const currentType = form.getValues('task_type') as TaskType
    if (!selectedSite.data_types.includes(currentType)) {
      const fallback =
        selectedSite.data_types.find((t) => TASK_TYPES.includes(t as TaskType)) ??
        TASK_TYPES[0]
      form.setValue('task_type', fallback as TaskType)
    }
  }, [selectedSite, form])

  const onSubmit = form.handleSubmit(async (values) => {
    try {
      await createFetchTask({
        task_type: values.task_type,
        source_key: values.source_key,
        domain: values.domain || undefined,
        fetch_strategy:
          !values.fetch_strategy || values.fetch_strategy === 'auto'
            ? undefined
            : values.fetch_strategy,
      })
      toast.success('采集任务已创建')
      form.reset(FORM_DEFAULTS)
      void load()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '创建失败')
    }
  })

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>手动触发采集</CardTitle>
          <CardDescription>采集策略缺省时由编排层按站点配置自动降级</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={(e) => void onSubmit(e)} className="flex flex-wrap items-end gap-3">
            <div className="w-44 space-y-1.5">
              <Label htmlFor="task_type">任务类型</Label>
              <Controller
                control={form.control}
                name="task_type"
                render={({ field }) => (
                  <Select
                    value={field.value}
                    onValueChange={field.onChange}
                    disabled={!selectedSite}
                  >
                    <SelectTrigger id="task_type">
                      <SelectValue placeholder={selectedSite ? undefined : '请先选择站点'} />
                    </SelectTrigger>
                    <SelectContent>
                      {(selectedSite?.data_types ?? []).map((t) => (
                        <SelectItem key={t} value={t}>
                          {TASK_TYPE_LABELS[t as TaskType] ?? t}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
            </div>

            <div className="w-52 space-y-1.5">
              <Label htmlFor="source_key">采集站点</Label>
              <Controller
                control={form.control}
                name="source_key"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger id="source_key">
                      <SelectValue placeholder="请选择站点" />
                    </SelectTrigger>
                    <SelectContent>
                      {sites.map((s) => (
                        <SelectItem key={s.key} value={s.key}>
                          {s.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
              {form.formState.errors.source_key && (
                <p className="text-xs text-red-600">{form.formState.errors.source_key.message}</p>
              )}
            </div>

            <div className="w-36 space-y-1.5">
              <Label htmlFor="domain">领域</Label>
              <Input id="domain" readOnly placeholder="随站点联动" {...form.register('domain')} />
            </div>

            <div className="w-44 space-y-1.5">
              <Label htmlFor="fetch_strategy">采集策略</Label>
              <Controller
                control={form.control}
                name="fetch_strategy"
                render={({ field }) => (
                  <Select value={field.value ?? 'auto'} onValueChange={field.onChange}>
                    <SelectTrigger id="fetch_strategy">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="auto">自动降级（默认）</SelectItem>
                      <SelectItem value="api">官方 API</SelectItem>
                      <SelectItem value="reverse_api">逆向接口</SelectItem>
                      <SelectItem value="playwright">Playwright</SelectItem>
                    </SelectContent>
                  </Select>
                )}
              />
            </div>

            <Button type="submit" disabled={form.formState.isSubmitting}>
              {form.formState.isSubmitting ? '提交中…' : '触发采集'}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>任务列表</CardTitle>
          <CardDescription>共 {total} 个任务，每 10 秒自动刷新</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>站点</TableHead>
                <TableHead>类型</TableHead>
                <TableHead>领域</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>尝试/命中</TableHead>
                <TableHead>策略</TableHead>
                <TableHead>错误信息</TableHead>
                <TableHead>创建时间</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tasks.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="text-center text-muted-foreground">
                    暂无任务
                  </TableCell>
                </TableRow>
              ) : (
                tasks.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell className="font-medium">{t.source_key}</TableCell>
                    <TableCell>{t.task_type}</TableCell>
                    <TableCell>{t.domain ?? '-'}</TableCell>
                    <TableCell>
                      <StatusBadge status={t.status} />
                    </TableCell>
                    <TableCell>
                      {t.attempt_count} / {t.hit_count}
                    </TableCell>
                    <TableCell>{t.fetch_strategy ?? '自动'}</TableCell>
                    <TableCell
                      className="max-w-48 truncate text-muted-foreground"
                      title={t.error_message ?? undefined}
                    >
                      {t.error_message ?? '-'}
                    </TableCell>
                    <TableCell>{formatTime(t.created_at)}</TableCell>
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
