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
    } else if (key === 'benchmark_score') {
      cmp = Number(a.benchmark_score) - Number(b.benchmark_score)
    } else if (key === 'updated_at') {
      cmp = a.updated_at.localeCompare(b.updated_at)
    } else {
      // 动态维度分：从 scores 取，null 排最后
      const av = a.scores?.[key]
      const bv = b.scores?.[key]
      if (av === null || av === undefined) cmp = bv === null || bv === undefined ? 0 : 1
      else if (bv === null || bv === undefined) cmp = -1
      else cmp = Number(av) - Number(bv)
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
        : { key, desc: !TEXT_KEYS.has(key) },
    )
    setPage(1)
  }

  return { rows, sort, toggleSort, page: safePage, setPage, pageCount, total: sorted.length }
}
