import { apiFetch, type Page } from './client'

/** 订阅套餐（与后端 PlanOut 对齐；monthly_price 为 Decimal 序列化后的字符串） */
export interface Plan {
  id: string
  provider: string
  plan_key: string
  plan_name: string
  monthly_price: string
  currency: string
  billing_cycle: string
  is_active: boolean
  source: string
  data: Record<string, unknown>
  updated_at: string
}

/** 订阅套餐列表，可按 provider 过滤 */
export function listPlans(provider?: string, page = 1, pageSize = 50) {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (provider) params.set('provider', provider)
  return apiFetch<Page<Plan>>(`/subscription-plans?${params.toString()}`)
}
