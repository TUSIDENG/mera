import { z } from 'zod'
import { apiFetch, type Page } from './client'

/** 采集任务（与后端 FetchTaskOut 对齐） */
export interface FetchTask {
  id: string
  task_type: string
  source_key: string
  domain: string | null
  triggered_by: string
  status: string
  attempt_count: number
  hit_count: number
  auto_start: boolean
  fetch_strategy: string | null
  error_message: string | null
  data: Record<string, unknown>
  created_at: string
  updated_at: string
}

/** 采集站点与默认 domain 的联动配置（与 M02 业务键一致） */
export const SOURCE_OPTIONS = [
  { value: 'openrouter', label: 'OpenRouter', domain: 'general' },
  { value: 'artificial_analysis', label: 'Artificial Analysis', domain: 'general' },
  { value: 'lmarena', label: 'LMArena', domain: 'chat' },
  { value: 'aider_leaderboard', label: 'Aider Leaderboard', domain: 'coding' },
] as const

export type SourceKey = (typeof SOURCE_OPTIONS)[number]['value']

export const DOMAIN_LABELS: Record<string, string> = {
  general: '通用',
  chat: '对话',
  coding: '代码',
}

/**
 * 手动触发采集表单 schema（纯函数，可单测）。
 * fetch_strategy 的 'auto' 为表单占位值，提交时转为 undefined（由编排层自动降级）。
 */
export const fetchTaskFormSchema = z.object({
  task_type: z.enum(['model_metrics', 'infrastructure_cost']),
  source_key: z.string().min(1, '请选择采集站点'),
  domain: z.string().max(50).optional(),
  fetch_strategy: z.union([z.enum(['api', 'reverse_api', 'playwright']), z.literal('auto')]).optional(),
})

export type FetchTaskFormValues = z.infer<typeof fetchTaskFormSchema>

/** 创建采集任务的请求体（与后端 FetchTaskCreate 对齐） */
export interface FetchTaskCreateBody {
  task_type: 'model_metrics' | 'infrastructure_cost'
  source_key: string
  domain?: string
  fetch_strategy?: 'api' | 'reverse_api' | 'playwright'
}

export function listFetchTasks(status?: string, page = 1, pageSize = 20) {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (status) params.set('status', status)
  return apiFetch<Page<FetchTask>>(`/fetch-tasks?${params.toString()}`)
}

export function createFetchTask(body: FetchTaskCreateBody) {
  return apiFetch<FetchTask>('/fetch-tasks', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}
