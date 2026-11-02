/** 统一 API client：注入 Bearer token、401 清理登录态并跳转、解析 {code,message} 错误体 */
import { useAuthStore } from '../stores/auth'

/** 后端统一分页响应 */
export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export class ApiError extends Error {
  readonly code: string
  readonly status: number

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

const BASE = '/api/v1'

/** 401 时跳转登录页（独立导出便于测试替换 location） */
export function redirectToLogin(): void {
  window.location.href = '/login'
}

async function parseError(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as { code?: string; message?: string }
    return new ApiError(
      res.status,
      body.code ?? 'unknown',
      body.message ?? `请求失败（HTTP ${res.status}）`,
    )
  } catch {
    return new ApiError(res.status, 'unknown', `请求失败（HTTP ${res.status}）`)
  }
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = useAuthStore.getState().token
  const headers = new Headers(init.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const res = await fetch(`${BASE}${path}`, { ...init, headers })
  if (res.status === 401) {
    useAuthStore.getState().logout()
    redirectToLogin()
    throw new ApiError(401, 'unauthorized', '登录已过期，请重新登录')
  }
  if (!res.ok) throw await parseError(res)
  return (await res.json()) as T
}
