import { apiFetch, type Page } from './client'

/** 榜单快照（与后端 SnapshotOut 对齐；benchmark_score 为 Decimal 序列化后的字符串） */
export interface Snapshot {
  id: string
  model_id: string
  provider: string
  domain: string
  benchmark_score: string | null
  /** 各维度分（intelligence/coding/agentic/image/video 等，LLM 打分后为其产出值，缺失为 null） */
  scores: Record<string, number | null>
  /** 主榜分来源：score/维度名 为采集回落，llm:<provider>/<model> 为 LLM 离线打分 */
  score_source: string | null
  /** data.sources 为各平台采集详情，data.llm_score 为 LLM 打分留痕 */
  data: Record<string, unknown>
  updated_at: string
}

/** 单平台采集条目（Snapshot.data.sources 的值） */
export interface SourceEntry {
  raw_model_id: string | null
  score_raw?: unknown
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
  domain: string
  record: Record<string, unknown>
  created_at: string
}

/** 按 domain 拉取榜单（默认拉满 100 条做客户端排序/分页） */
export function listModels(domain: string, page = 1, pageSize = 100) {
  return apiFetch<Page<Snapshot>>(
    `/models?domain=${encodeURIComponent(domain)}&page=${page}&page_size=${pageSize}`,
  )
}

/** 单模型全部 domain 的历史快照 */
export function listModelSnapshots(modelId: string) {
  return apiFetch<Snapshot[]>(`/models/${encodeURIComponent(modelId)}/snapshots`)
}

/** 单模型采集历史（按时间倒序） */
export function listModelFetchRecords(modelId: string, page = 1, pageSize = 50) {
  return apiFetch<Page<FetchRecord>>(
    `/models/${encodeURIComponent(modelId)}/fetch-records?page=${page}&page_size=${pageSize}`,
  )
}
