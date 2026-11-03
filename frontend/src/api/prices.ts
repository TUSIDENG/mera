import { apiFetch, type Page } from './client'

/** API 按量价格（与后端 PriceOut 对齐；价格为每 unit 单价，Decimal 序列化字符串） */
export interface ApiPrice {
  id: string
  model_id: string
  provider: string
  input_price: string | null
  output_price: string | null
  currency: string
  unit: string
  source: string
  is_active: boolean
  data: Record<string, unknown>
  updated_at: string
}

/** 活跃 API 价格列表，可按 provider 过滤 */
export function listApiPrices(provider?: string, page = 1, pageSize = 100) {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (provider) params.set('provider', provider)
  return apiFetch<Page<ApiPrice>>(`/api-prices?${params.toString()}`)
}
