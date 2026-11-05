import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Snapshot } from '../api/models'
import { sortItems, useLeaderboardTable, type RankedSnapshot } from './useLeaderboardTable'

function makeSnapshot(modelId: string, score: string, updatedAt = '2026-01-01T00:00:00Z'): Snapshot {
  return {
    id: modelId,
    model_id: modelId,
    provider: 'p-' + modelId,
    benchmark_score: score,
    scores: {},
    score_source: 'score',
    data: {},
    updated_at: updatedAt,
  }
}

const RANKED: RankedSnapshot[] = [
  { ...makeSnapshot('a-model', '90'), rank: 1 },
  { ...makeSnapshot('b-model', '95'), rank: 2 },
  { ...makeSnapshot('c-model', '85'), rank: 3 },
]

describe('sortItems', () => {
  it('按分数降序', () => {
    const sorted = sortItems(RANKED, { key: 'benchmark_score', desc: true })
    expect(sorted.map((s) => s.model_id)).toEqual(['b-model', 'a-model', 'c-model'])
  })

  it('按分数升序', () => {
    const sorted = sortItems(RANKED, { key: 'benchmark_score', desc: false })
    expect(sorted.map((s) => s.model_id)).toEqual(['c-model', 'a-model', 'b-model'])
  })

  it('按 model_id 字典序', () => {
    const sorted = sortItems(RANKED, { key: 'model_id', desc: false })
    expect(sorted.map((s) => s.model_id)).toEqual(['a-model', 'b-model', 'c-model'])
  })
})

describe('useLeaderboardTable', () => {
  it('默认按分数降序，toggleSort 同列翻转方向', () => {
    const { result } = renderHook(() =>
      useLeaderboardTable(RANKED.map(({ rank: _rank, ...s }) => s)),
    )
    expect(result.current.rows.map((r) => r.model_id)).toEqual(['b-model', 'a-model', 'c-model'])

    act(() => result.current.toggleSort('benchmark_score'))
    expect(result.current.rows.map((r) => r.model_id)).toEqual(['c-model', 'a-model', 'b-model'])

    // 切换到文本列：默认升序
    act(() => result.current.toggleSort('model_id'))
    expect(result.current.sort).toEqual({ key: 'model_id', desc: false })
    expect(result.current.rows.map((r) => r.model_id)).toEqual(['a-model', 'b-model', 'c-model'])
  })

  it('分页：pageSize=2 时首页 2 条、共 2 页', () => {
    const { result } = renderHook(() =>
      useLeaderboardTable(
        RANKED.map(({ rank: _rank, ...s }) => s),
        2,
      ),
    )
    expect(result.current.rows).toHaveLength(2)
    expect(result.current.pageCount).toBe(2)

    act(() => result.current.setPage(2))
    expect(result.current.rows).toHaveLength(1)
    expect(result.current.rows[0].model_id).toBe('c-model')
  })
})
