import { describe, expect, it } from 'vitest'
import { fetchTaskFormSchema, SOURCE_OPTIONS } from './tasks'

describe('fetchTaskFormSchema', () => {
  it('合法表单通过校验', () => {
    const result = fetchTaskFormSchema.safeParse({
      task_type: 'model_metrics',
      source_key: 'openrouter',
      domain: 'general',
      fetch_strategy: 'auto',
    })
    expect(result.success).toBe(true)
  })

  it('source_key 必填', () => {
    expect(
      fetchTaskFormSchema.safeParse({ task_type: 'model_metrics', source_key: '' }).success,
    ).toBe(false)
    expect(fetchTaskFormSchema.safeParse({ task_type: 'model_metrics' }).success).toBe(false)
  })

  it('非法 task_type 被拒绝', () => {
    expect(
      fetchTaskFormSchema.safeParse({ task_type: 'hack', source_key: 'openrouter' }).success,
    ).toBe(false)
  })

  it('fetch_strategy 仅允许 api/reverse_api/playwright/auto', () => {
    expect(
      fetchTaskFormSchema.safeParse({
        task_type: 'model_metrics',
        source_key: 'openrouter',
        fetch_strategy: 'playwright',
      }).success,
    ).toBe(true)
    expect(
      fetchTaskFormSchema.safeParse({
        task_type: 'model_metrics',
        source_key: 'openrouter',
        fetch_strategy: 'selenium',
      }).success,
    ).toBe(false)
  })

  it('SOURCE_OPTIONS 覆盖四个站点且 domain 联动正确', () => {
    expect(SOURCE_OPTIONS.map((o) => o.value)).toEqual([
      'openrouter',
      'artificial_analysis',
      'lmarena',
      'aider_leaderboard',
    ])
    expect(SOURCE_OPTIONS.find((o) => o.value === 'lmarena')?.domain).toBe('chat')
    expect(SOURCE_OPTIONS.find((o) => o.value === 'aider_leaderboard')?.domain).toBe('coding')
  })
})
