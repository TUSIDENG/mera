import { apiFetch } from './client'

/** 采集站点元数据（与后端 SiteOut 对齐） */
export interface CollectionSite {
  key: string
  label: string
  domain: string | null
  data_type: string
  /** 该站点支持的任务类型（前端据此过滤 task_type 选项） */
  data_types: string[]
}

export function listSites() {
  return apiFetch<CollectionSite[]>('/sites')
}
