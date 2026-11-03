import { describe, expect, it } from 'vitest'
import { fetchTaskFormSchema, TASK_TYPES } from './tasks'

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

  it('TASK_TYPES 覆盖四种数据域', () => {
    // 站点列表改由后端 /api/v1/sites 动态返回，前端仅维护任务类型枚举
    expect(TASK_TYPES).toEqual([
      'model_metrics',
      'api_price',
      'infrastructure_cost',
      'subscription_plan',
    ])
  })
})
