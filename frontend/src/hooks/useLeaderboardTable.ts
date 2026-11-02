import { useMemo, useState } from 'react'
import type { Snapshot } from '../api/models'

export type SortKey = 'rank' | 'model_id' | 'provider' | 'benchmark_score' | 'updated_at'

export interface SortState {
  key: SortKey
  desc: boolean
}

/** 附带榜单排名（按接口返回顺序，后端已按分数降序） */
export type RankedSnapshot = Snapshot & { rank: number }

/** 纯排序逻辑（与 UI 分离，便于单测） */
export function sortItems(items: RankedSnapshot[], sort: SortState): RankedSnapshot[] {
  const dir = sort.desc ? -1 : 1
  return [...items].sort((a, b) => {
    let cmp = 0
    switch (sort.key) {
      case 'rank':
        cmp = a.rank - b.rank
        break
      case 'model_id':
        cmp = a.model_id.localeCompare(b.model_id)
        break
      case 'provider':
        cmp = a.provider.localeCompare(b.provider)
        break
      case 'benchmark_score':
        cmp = Number(a.benchmark_score) - Number(b.benchmark_score)
        break
      case 'updated_at':
        cmp = a.updated_at.localeCompare(b.updated_at)
        break
    }
    return cmp * dir
  })
}

/** 榜单表格：客户端排序 + 分页 */
export function useLeaderboardTable(items: Snapshot[], pageSize = 20) {
  const [sort, setSort] = useState<SortState>({ key: 'benchmark_score', desc: true })
  const [page, setPage] = useState(1)

  const ranked = useMemo<RankedSnapshot[]>(
    () => items.map((s, i) => ({ ...s, rank: i + 1 })),
    [items],
  )
  const sorted = useMemo(() => sortItems(ranked, sort), [ranked, sort])
  const pageCount = Math.max(1, Math.ceil(sorted.length / pageSize))
  const safePage = Math.min(page, pageCount)
  const rows = useMemo(
    () => sorted.slice((safePage - 1) * pageSize, safePage * pageSize),
    [sorted, safePage, pageSize],
  )

  const toggleSort = (key: SortKey) => {
    setSort((prev) =>
      // 文本列默认升序，数值/时间列默认降序；同列再次点击翻转
      prev.key === key
        ? { key, desc: !prev.desc }
        : { key, desc: key !== 'model_id' && key !== 'provider' },
    )
    setPage(1)
  }

  return { rows, sort, toggleSort, page: safePage, setPage, pageCount, total: sorted.length }
}
