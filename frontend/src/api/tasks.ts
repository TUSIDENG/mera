import { z } from 'zod'
import { apiFetch, type Page } from './client'
import type { FetchRecord } from './models'

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

/** 任务类型取值集合（与后端 FetchTaskType 对齐） */
export const TASK_TYPES = [
  'model_metrics',
  'api_price',
  'infrastructure_cost',
  'subscription_plan',
] as const

export type TaskType = (typeof TASK_TYPES)[number]

/** 任务类型中文名（用于前端下拉展示） */
export const TASK_TYPE_LABELS: Record<TaskType, string> = {
  model_metrics: '模型指标（榜单）',
  api_price: 'API 价格',
  infrastructure_cost: '基础设施成本',
  subscription_plan: '订阅套餐',
}

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
  task_type: z.enum(TASK_TYPES),
  source_key: z.string().min(1, '请选择采集站点'),
  domain: z.string().max(50).optional(),
  fetch_strategy: z.union([z.enum(['api', 'reverse_api', 'playwright']), z.literal('auto')]).optional(),
})

export type FetchTaskFormValues = z.infer<typeof fetchTaskFormSchema>

/** 创建采集任务的请求体（与后端 FetchTaskCreate 对齐） */
export interface FetchTaskCreateBody {
  task_type: TaskType
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

/** 任务维度采集留痕（按时间倒序） */
export function listFetchTaskRecords(taskId: string, page = 1, pageSize = 50) {
  return apiFetch<Page<FetchRecord>>(
    `/fetch-tasks/${taskId}/records?page=${page}&page_size=${pageSize}`,
  )
}

