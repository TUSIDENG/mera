import { apiFetch, type Page } from './client'

/** 榜单快照（与后端 SnapshotOut 对齐；benchmark_score 为 Decimal 序列化后的字符串） */
export interface Snapshot {
  id: string
  model_id: string
  provider: string
  benchmark_score: string | null
  /** 各维度分（intelligence/coding/agentic/long_context/image/video），缺失为 null */
  scores: Record<string, number | null>
  /** 主榜分来源：<来源>:<维度> 为采集聚合，llm:<provider>/<model> 为 LLM 离线打分 */
  score_source: string | null
  /** data.sources 为各平台采集详情，data.llm_score 为 LLM 打分留痕 */
  data: Record<string, unknown>
  updated_at: string
}

/** 单平台采集条目（Snapshot.data.sources 的值） */
export interface SourceEntry {
  raw_model_id: string | null
  /** 该来源所属榜单域（溯源用） */
  domain?: string
  score_raw?: unknown
  benchmark_score?: number | null
  scores?: Record<string, number | null>
  score_source?: string | null
  record: Record<string, unknown>
}

/** LLM 打分留痕（Snapshot.data.llm_score） */
export interface LlmScore {
  overall: number | null
  dims: Record<string, number | null>
  rationale: string
  scorer: string
  scored_at: string
}

/** 采集留痕行（与后端 FetchRecordOut 对齐）：哪次任务、从哪个平台、采了什么 */
export interface FetchRecord {
  id: string
  task_id: string
  source_key: string
  model_id: string
  raw_model_id: string | null
  record: Record<string, unknown>
  created_at: string
}

/** 拉取榜单（一个模型一行，默认拉满 100 条做客户端排序/分页） */
export function listModels(page = 1, pageSize = 100) {
  return apiFetch<Page<Snapshot>>(`/models?page=${page}&page_size=${pageSize}`)
}

/** 榜单页最多展示的模型数（后端单页上限 100，超出部分按页补齐） */
export const LEADERBOARD_MODEL_LIMIT = 300

/** 拉取榜单前 limit 个模型：按后端分页上限循环取页，避免一次请求过大 */
export async function listTopModels(limit = LEADERBOARD_MODEL_LIMIT): Promise<Page<Snapshot>> {
  const pageSize = 100
  const first = await listModels(1, pageSize)
  const items = [...first.items]
  let page = 1
  while (items.length < limit && items.length < first.total) {
    page += 1
    const next = await listModels(page, pageSize)
    if (next.items.length === 0) break
    items.push(...next.items)
  }
  return { ...first, items: items.slice(0, limit) }
}

/** 单模型当前快照（一个模型一行，返回 0 或 1 条） */
export function listModelSnapshots(modelId: string) {
  return apiFetch<Snapshot[]>(`/models/${encodeURIComponent(modelId)}/snapshots`)
}

/** 单模型采集历史（按时间倒序） */
export function listModelFetchRecords(modelId: string, page = 1, pageSize = 50) {
  return apiFetch<Page<FetchRecord>>(
    `/models/${encodeURIComponent(modelId)}/fetch-records?page=${page}&page_size=${pageSize}`,
  )
}
