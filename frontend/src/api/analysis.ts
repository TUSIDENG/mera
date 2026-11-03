import { z } from 'zod'
import { apiFetch } from './client'

/** 单个模型排名结果（与后端 RankedModelOut 对齐） */
export interface RankedModel {
  model_id: string
  provider: string
  display_name: string | null
  benchmark_score: number
  benchmark_norm: number
  price_norm: number
  monthly_cost: number | null
  composite_score: number
  rank: number
}

/** 分析结果（与后端 AnalysisRunResponse 对齐） */
export interface AnalysisRunResponse {
  domain: string
  items: RankedModel[]
  total: number
}

/**
 * 分析表单 schema：权重只暴露 benchmark_weight 单一滑块，
 * price_weight 提交时按 1 - benchmark_weight 计算，天然满足后端「权重和为 1」约束。
 */
export const analysisFormSchema = z.object({
  domain: z.string().min(1, '请选择领域'),
  benchmark_weight: z.number().min(0).max(1),
  tokens_per_month: z.number().int('月用量必须为整数').min(1, '月用量至少为 1'),
  input_ratio: z.number().min(0).max(1),
})

export type AnalysisFormValues = z.infer<typeof analysisFormSchema>

/** 分析请求体（与后端 AnalysisRunRequest 对齐） */
export interface AnalysisRunBody {
  domain: string
  benchmark_weight: number
  price_weight: number
  tokens_per_month: number
  input_ratio: number
}

/** 表单值 → 请求体：price_weight = 1 - benchmark_weight（截断浮点尾差） */
export function toRunBody(values: AnalysisFormValues): AnalysisRunBody {
  return {
    domain: values.domain,
    benchmark_weight: values.benchmark_weight,
    price_weight: Number((1 - values.benchmark_weight).toFixed(6)),
    tokens_per_month: values.tokens_per_month,
    input_ratio: values.input_ratio,
  }
}

/** 触发加权分析（M09 引擎） */
export function runAnalysis(body: AnalysisRunBody) {
  return apiFetch<AnalysisRunResponse>('/analysis/run', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}
