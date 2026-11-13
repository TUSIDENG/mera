import { useMemo, useState } from 'react'
import type { Snapshot } from '../api/models'

/** 排序键：固定列 + 任意维度名（scores 中的 key） */
export type SortKey = string

export interface SortState {
  key: SortKey
  desc: boolean
}

/** 文本列（默认升序），其余数值/时间列默认降序 */
const TEXT_KEYS = new Set(['model_id', 'provider'])

/** 附带榜单排名（按接口返回顺序，后端已按分数降序） */
export type RankedSnapshot = Snapshot & { rank: number }

/** 纯排序逻辑（与 UI 分离，便于单测） */
export function sortItems(items: RankedSnapshot[], sort: SortState): RankedSnapshot[] {
  const dir = sort.desc ? -1 : 1
  return [...items].sort((a, b) => {
    let cmp = 0
    const key = sort.key
    if (key === 'rank') {
      cmp = a.rank - b.rank
    } else if (key === 'model_id') {
      cmp = a.model_id.localeCompare(b.model_id)
    } else if (key === 'provider') {
      cmp = a.provider.localeCompare(b.provider)
    } else if (key === 'updated_at') {
      cmp = a.updated_at.localeCompare(b.updated_at)
    } else {
      // 数值列（主榜分 / 维度分）：缺失值恒定排末尾，不随升/降序翻转
      const av = key === 'benchmark_score' ? a.benchmark_score : a.scores?.[key]
      const bv = key === 'benchmark_score' ? b.benchmark_score : b.scores?.[key]
      const aMissing = av === null || av === undefined || av === ''
      const bMissing = bv === null || bv === undefined || bv === ''
      if (aMissing || bMissing) {
        if (aMissing && bMissing) return 0
        return aMissing ? 1 : -1
      }
      cmp = Number(av) - Number(bv)
    }
    return cmp * dir
  })
}

/** 榜单表格：客户端排序 + 分页（每页条数可切换） */
export function useLeaderboardTable(items: Snapshot[], initialPageSize = 20) {
  const [sort, setSort] = useState<SortState>({ key: 'benchmark_score', desc: true })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSizeState] = useState(initialPageSize)

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
        : { key, desc: !TEXT_KEYS.has(key) },
    )
    setPage(1)
  }

  const setPageSize = (size: number) => {
    setPageSizeState(size)
    setPage(1) // 换每页条数后页码重置，避免停在越界页
  }

  return {
    rows,
    sort,
    toggleSort,
    page: safePage,
    setPage,
    pageCount,
    total: sorted.length,
    pageSize,
    setPageSize,
  }
}
