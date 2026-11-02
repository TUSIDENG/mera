import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}

/** 分数格式化：pydantic v2 将 Decimal 序列化为字符串，统一按数值保留两位小数 */
export function formatScore(score: string | number): string {
  const n = typeof score === 'string' ? Number(score) : score
  return Number.isFinite(n) ? n.toFixed(2) : String(score)
}

/** ISO 时间格式化（失败时原样返回） */
export function formatTime(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('zh-CN', { hour12: false })
}
