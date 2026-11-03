import { apiFetch, type Page } from './client'

/** 榜单快照（与后端 SnapshotOut 对齐；benchmark_score 为 Decimal 序列化后的字符串） */
export interface Snapshot {
  id: string
  model_id: string
  provider: string
  domain: string
  benchmark_score: string | null
  /** 各维度原始分（如 { intelligence: 51, coding: 70.1, agentic: null }） */
  scores: Record<string, number | null>
  /** 主榜分来源维度（score/intelligence/coding/agentic），缺失为 null */
  score_source: string | null
  data: Record<string, unknown>
  updated_at: string
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
