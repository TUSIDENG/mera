import { fireEvent, render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { useAuthStore } from '../stores/auth'
import { server } from '../test/server'
import { analysisFormSchema, toRunBody } from '../api/analysis'
import { formatCost } from '../lib/utils'
import AnalysisPage from './AnalysisPage'

const RANKED = {
  total: 2,
  items: [
    {
      model_id: 'gpt-4o',
      provider: 'openai',
      display_name: 'OpenAI: GPT-4o',
      benchmark_score: 95.5,
      benchmark_norm: 1,
      price_norm: 0.2,
      monthly_cost: 3.5,
      composite_score: 0.68,
      rank: 1,
    },
    {
      model_id: 'claude-4',
      provider: 'anthropic',
      display_name: null,
      benchmark_score: 90.1,
      benchmark_norm: 0,
      price_norm: 1,
      monthly_cost: 0.1234,
      composite_score: 0.4,
      rank: 2,
    },
  ],
}

describe('analysis schema', () => {
  it('toRunBody：price_weight 与 benchmark_weight 互补', () => {
    const body = toRunBody({
      benchmark_weight: 0.6,
      tokens_per_month: 1_000_000,
      input_ratio: 0.7,
    })
    expect(body.price_weight).toBeCloseTo(0.4)
    expect(body.benchmark_weight + body.price_weight).toBeCloseTo(1)
  })

  it('schema 拒绝非法月用量', () => {
    expect(
      analysisFormSchema.safeParse({
        benchmark_weight: 0.6,
        tokens_per_month: 0,
        input_ratio: 0.7,
      }).success,
    ).toBe(false)
  })

  it('formatCost：缺项与大额小额分支', () => {
    expect(formatCost(null)).toBe('-')
    expect(formatCost(0.1234)).toBe('$0.1234')
    expect(formatCost(3.5)).toBe('$3.50')
  })
})

describe('AnalysisPage', () => {
  beforeEach(() => {
    useAuthStore.getState().login('token-test', 3600)
  })

  it('提交默认表单后渲染推荐排名', async () => {
    server.use(http.post('/api/v1/analysis/run', () => HttpResponse.json(RANKED)))

    render(
      <MemoryRouter>
        <AnalysisPage />
      </MemoryRouter>,
    )
    fireEvent.click(screen.getByRole('button', { name: '开始分析' }))

    // display_name 优先，缺省回退 model_id
    expect(await screen.findByText('OpenAI: GPT-4o')).toBeInTheDocument()
    expect(screen.getByText('claude-4')).toBeInTheDocument()
    expect(screen.getByText('0.680')).toBeInTheDocument()
    expect(screen.getByText('$3.50')).toBeInTheDocument()
    expect(screen.getByText('$0.1234')).toBeInTheDocument()
  })

  it('后端 422 时展示错误消息', async () => {
    server.use(
      http.post('/api/v1/analysis/run', () =>
        HttpResponse.json(
          { code: 'invalid_weights', message: '权重之和必须为 1，当前为 1.5' },
          { status: 422 },
        ),
      ),
    )

    render(
      <MemoryRouter>
        <AnalysisPage />
      </MemoryRouter>,
    )
    fireEvent.click(screen.getByRole('button', { name: '开始分析' }))

    expect(
      await screen.findByText(/权重之和必须为 1/),
    ).toBeInTheDocument()
  })
})
