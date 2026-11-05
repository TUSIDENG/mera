import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from '@tanstack/react-table'
import { ArrowDown, ArrowUp, ArrowUpDown, Info } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { listModels, type Snapshot } from '../api/models'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { Skeleton } from '../components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table'
import {
  useLeaderboardTable,
  type RankedSnapshot,
  type SortKey,
} from '../hooks/useLeaderboardTable'
import { formatScore, formatTime } from '../lib/utils'

/** 榜单固定维度列（一个模型一行，各维度均由 LLM 基于采集数据评定，缺失显示 -） */
const DIMENSIONS = ['intelligence', 'coding', 'agentic', 'long_context', 'image', 'video']

/** 维度中文名与说明（悬浮展示） */
const DIMENSION_META: Record<string, { label: string; desc: string }> = {
  score: { label: '综合分', desc: '站点原始总分（不同站点口径不同，不可直接跨站比较）' },
  intelligence: { label: '智力', desc: '综合推理与知识能力（LLM 基于采集数据评定）' },
  coding: { label: '编程', desc: '代码生成与软件工程能力（LLM 基于采集数据评定）' },
  agentic: { label: '智能体', desc: '工具调用与自主任务能力（LLM 基于采集数据评定）' },
  long_context: { label: '长上下文', desc: '长上下文与长文档处理能力（LLM 基于采集数据评定，无数据为 -）' },
  image: { label: '图像生成', desc: '图像生成能力（LLM 基于采集数据评定，无数据为 -）' },
  video: { label: '视频生成', desc: '视频生成能力（LLM 基于采集数据评定，无数据为 -）' },
}

function dimLabel(key: string): string {
  return DIMENSION_META[key]?.label ?? key
}

function dimDesc(key: string): string {
  return DIMENSION_META[key]?.desc ?? key
}

export default function LeaderboardPage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<Snapshot[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedProviders, setSelectedProviders] = useState<Set<string>>(new Set())

  useEffect(() => {
    setLoading(true)
    listModels()
      .then((res) => {
        setItems(res.items)
        // 重置平台筛选
        setSelectedProviders(new Set())
      })
      .catch((e: unknown) =>
        toast.error(e instanceof Error ? e.message : '榜单加载失败'),
      )
      .finally(() => setLoading(false))
  }, [])

  // 固定维度列：即使当前数据缺失也稳定展示，缺失为 -
  const dimensions = DIMENSIONS

  // 平台列表（按字母序）
  const providers = useMemo(() => {
    const set = new Set(items.map((i) => i.provider))
    return Array.from(set).sort()
  }, [items])

  // 平台过滤后的数据
  const filteredItems = useMemo(() => {
    if (selectedProviders.size === 0) return items
    return items.filter((i) => selectedProviders.has(i.provider))
  }, [items, selectedProviders])

  const toggleProvider = (p: string) => {
    setSelectedProviders((prev) => {
      const next = new Set(prev)
      if (next.has(p)) next.delete(p)
      else next.add(p)
      return next
    })
  }

  const { rows, sort, toggleSort, page, setPage, pageCount, total } =
    useLeaderboardTable(filteredItems)

  // 动态列：固定列 + 维度列 + 主榜分 + 更新时间
  const columns = useMemo<ColumnDef<RankedSnapshot>[]>(() => {
    const cols: ColumnDef<RankedSnapshot>[] = [
      { accessorKey: 'rank', header: '排名' },
      { accessorKey: 'model_id', header: '模型' },
      { accessorKey: 'provider', header: '厂商' },
    ]
    for (const dim of dimensions) {
      cols.push({
        accessorKey: `scores.${dim}`,
        header: () => (
          <span className="inline-flex items-center gap-1" title={dimDesc(dim)}>
            {dimLabel(dim)}
            <Info className="h-3 w-3 text-muted-foreground" />
          </span>
        ),
        cell: ({ row }) => {
          const v = row.original.scores?.[dim]
          return v === null || v === undefined ? (
            <span className="text-muted-foreground">-</span>
          ) : (
            formatScore(v)
          )
        },
      })
    }
    cols.push({
      accessorKey: 'benchmark_score',
      header: '主榜分',
      cell: ({ row }) =>
        row.original.benchmark_score === null ? (
          <span className="text-muted-foreground">-</span>
        ) : (
          formatScore(row.original.benchmark_score)
        ),
    })
    cols.push({
      accessorKey: 'updated_at',
      header: '更新时间',
      cell: ({ row }) => formatTime(row.original.updated_at),
    })
    return cols
  }, [dimensions])

  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle>模型榜单</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* 平台多选筛选 */}
        {!loading && providers.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-muted-foreground">平台：</span>
            <Button
              variant={selectedProviders.size === 0 ? 'default' : 'outline'}
              size="sm"
              onClick={() => setSelectedProviders(new Set())}
            >
              全部
            </Button>
            {providers.map((p) => (
              <Button
                key={p}
                variant={selectedProviders.has(p) ? 'default' : 'outline'}
                size="sm"
                onClick={() => toggleProvider(p)}
              >
                {p}
              </Button>
            ))}
          </div>
        )}

        {loading ? (
          <div className="space-y-2">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : (
          <>
            <Table>
              <TableHeader>
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {headerGroup.headers.map((header) => {
                      const key = header.column.id as SortKey
                      const active = sort.key === key
                      return (
                        <TableHead key={header.id}>
                          <button
                            type="button"
                            className="inline-flex items-center gap-1 hover:text-foreground"
                            onClick={() => toggleSort(key)}
                          >
                            {flexRender(header.column.columnDef.header, header.getContext())}
                            {active ? (
                              sort.desc ? (
                                <ArrowDown className="h-3.5 w-3.5" />
                              ) : (
                                <ArrowUp className="h-3.5 w-3.5" />
                              )
                            ) : (
                              <ArrowUpDown className="h-3.5 w-3.5 opacity-40" />
                            )}
                          </button>
                        </TableHead>
                      )
                    })}
                  </TableRow>
                ))}
              </TableHeader>
              <TableBody>
                {table.getRowModel().rows.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={columns.length} className="text-center text-muted-foreground">
                      暂无数据，可在「采集任务」页手动触发采集
                    </TableCell>
                  </TableRow>
                ) : (
                  table.getRowModel().rows.map((row) => (
                    <TableRow
                      key={row.id}
                      className="cursor-pointer"
                      onClick={() =>
                        navigate(`/models/${encodeURIComponent(row.original.model_id)}`)
                      }
                    >
                      {row.getVisibleCells().map((cell) => (
                        <TableCell key={cell.id}>
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>

            <div className="flex items-center justify-between text-sm text-muted-foreground">
              <span>
                第 {page} / {pageCount} 页 · 共 {total} 条
                {selectedProviders.size > 0 && (
                  <Badge variant="secondary" className="ml-2">
                    已选 {selectedProviders.size} 个平台
                  </Badge>
                )}
              </span>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                  上一页
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= pageCount}
                  onClick={() => setPage(page + 1)}
                >
                  下一页
                </Button>
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
