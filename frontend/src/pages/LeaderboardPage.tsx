import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from '@tanstack/react-table'
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { listModels, type Snapshot } from '../api/models'
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
import { Tabs, TabsList, TabsTrigger } from '../components/ui/tabs'
import {
  useLeaderboardTable,
  type RankedSnapshot,
  type SortKey,
} from '../hooks/useLeaderboardTable'
import { formatScore, formatTime } from '../lib/utils'

const DOMAINS = [
  { key: 'general', label: '通用' },
  { key: 'chat', label: '对话' },
  { key: 'coding', label: '代码' },
]

const COLUMNS: ColumnDef<RankedSnapshot>[] = [
  { accessorKey: 'rank', header: '排名' },
  { accessorKey: 'model_id', header: '模型' },
  { accessorKey: 'provider', header: '厂商' },
  {
    accessorKey: 'benchmark_score',
    header: '分数',
    cell: ({ row }) => formatScore(row.original.benchmark_score),
  },
  {
    accessorKey: 'updated_at',
    header: '更新时间',
    cell: ({ row }) => formatTime(row.original.updated_at),
  },
]

export default function LeaderboardPage() {
  const navigate = useNavigate()
  const [domain, setDomain] = useState('general')
  const [items, setItems] = useState<Snapshot[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    listModels(domain)
      .then((res) => setItems(res.items))
      .catch((e: unknown) =>
        toast.error(e instanceof Error ? e.message : '榜单加载失败'),
      )
      .finally(() => setLoading(false))
  }, [domain])

  const { rows, sort, toggleSort, page, setPage, pageCount, total } =
    useLeaderboardTable(items)
  const columns = useMemo(() => COLUMNS, [])
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
        <Tabs value={domain} onValueChange={setDomain}>
          <TabsList>
            {DOMAINS.map((d) => (
              <TabsTrigger key={d.key} value={d.key}>
                {d.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>

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
                    <TableCell colSpan={COLUMNS.length} className="text-center text-muted-foreground">
                      暂无数据，可在「采集任务」页手动触发采集
                    </TableCell>
                  </TableRow>
                ) : (
                  table.getRowModel().rows.map((row) => (
                    <TableRow
                      key={row.id}
                      className="cursor-pointer"
                      onClick={() =>
                        // model_id 可能含 /（如 openai/gpt-4o），需编码为单个路径段
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
