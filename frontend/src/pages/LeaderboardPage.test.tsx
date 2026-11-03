import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { useAuthStore } from '../stores/auth'
import { server } from '../test/server'
import LeaderboardPage from './LeaderboardPage'

const SNAPSHOTS = [
  {
    id: '11111111-1111-1111-1111-111111111111',
    model_id: 'gpt-4o',
    provider: 'openai',
    domain: 'general',
    benchmark_score: '95.5',
    scores: { intelligence: 95.5, coding: null, agentic: null },
    score_source: 'intelligence',
    data: {},
    updated_at: '2026-01-02T00:00:00Z',
  },
  {
    id: '22222222-2222-2222-2222-222222222222',
    model_id: 'claude-4',
    provider: 'anthropic',
    domain: 'general',
    benchmark_score: '90.123',
    scores: { intelligence: 90.123, coding: 85, agentic: 70 },
    score_source: 'intelligence',
    data: {},
    updated_at: '2026-01-01T00:00:00Z',
  },
]

describe('LeaderboardPage', () => {
  beforeEach(() => {
    useAuthStore.getState().login('token-test', 3600)
  })

  it('渲染榜单：model_id 与格式化分数', async () => {
    server.use(
      http.get('/api/v1/models', () =>
        HttpResponse.json({ items: SNAPSHOTS, total: 2, page: 1, page_size: 100 }),
      ),
    )

    render(
      <MemoryRouter>
        <LeaderboardPage />
      </MemoryRouter>,
    )

    // model_id 渲染
    expect(await screen.findByText('gpt-4o')).toBeInTheDocument()
    expect(screen.getByText('claude-4')).toBeInTheDocument()
    // Decimal 字符串 → 两位小数格式化（维度列与主榜分列各出现一次）
    expect(screen.getAllByText('95.50').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('90.12').length).toBeGreaterThanOrEqual(1)
    // 厂商（平台筛选按钮与表格各出现一次）
    expect(screen.getAllByText('openai').length).toBeGreaterThanOrEqual(1)
  })

  it('接口报错时展示空态而不崩溃', async () => {
    server.use(
      http.get('/api/v1/models', () =>
        HttpResponse.json({ code: 'internal', message: 'boom' }, { status: 500 }),
      ),
    )

    render(
      <MemoryRouter>
        <LeaderboardPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/暂无数据/)).toBeInTheDocument()
  })
})
