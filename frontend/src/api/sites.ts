import { apiFetch } from './client'

/** 采集站点元数据（与后端 SiteOut 对齐） */
export interface CollectionSite {
  key: string
  label: string
  domain: string | null
  /** 站点覆盖的领域列表（多领域站点前端渲染领域下拉）；为空表示不区分领域 */
  domains: string[]
  data_type: string
  /** 该站点支持的任务类型（前端据此过滤 task_type 选项） */
  data_types: string[]
  /** 站点说明（可选） */
  description: string | null
  /** 站点官网地址（可选） */
  homepage: string | null
}

export function listSites() {
  return apiFetch<CollectionSite[]>('/sites')
}
