import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}

/** 分数格式化：pydantic v2 将 Decimal 序列化为字符串，统一按数值保留两位小数；null 显示 - */
export function formatScore(score: string | number | null): string {
  if (score === null) return '-'
  const n = typeof score === 'string' ? Number(score) : score
  return Number.isFinite(n) ? n.toFixed(2) : String(score)
}

/** ISO 时间格式化（失败时原样返回） */
export function formatTime(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('zh-CN', { hour12: false })
}

/** 月成本格式化：小额给 4 位小数避免全是 $0.00，缺项显示 - */
export function formatCost(value: number | null): string {
  if (value === null) return '-'
  return value < 1 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`
}

/** 每 token 单价格式化为每 1M token 价格（更易读）；缺项显示 - */
export function formatTokenPrice(price: string | number | null): string {
  if (price === null || price === undefined) return '-'
  const n = typeof price === 'string' ? Number(price) : price
  if (!Number.isFinite(n)) return '-'
  const perMillion = n * 1_000_000
  return `$${perMillion < 1 ? perMillion.toFixed(4) : perMillion.toFixed(2)}/MTok`
}
