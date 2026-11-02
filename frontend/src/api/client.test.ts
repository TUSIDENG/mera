import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../stores/auth'
import { ApiError, apiFetch } from './client'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('apiFetch', () => {
  const originalLocation = window.location

  beforeEach(() => {
    useAuthStore.getState().logout()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    Object.defineProperty(window, 'location', { value: originalLocation, configurable: true })
  })

  it('注入 Authorization: Bearer 头', async () => {
    useAuthStore.getState().login('token-abc', 3600)
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ ok: true }))

    await apiFetch('/models?domain=general&page=1&page_size=100')

    const [url, init] = fetchSpy.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/v1/models?domain=general&page=1&page_size=100')
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer token-abc')
  })

  it('401 清理 token 并跳转 /login', async () => {
    useAuthStore.getState().login('token-expired', 3600)
    const locationMock = { href: '' }
    Object.defineProperty(window, 'location', { value: locationMock, configurable: true })
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ code: 'unauthorized', message: 'bad token' }, 401),
    )

    await expect(apiFetch('/models?domain=general')).rejects.toBeInstanceOf(ApiError)
    expect(useAuthStore.getState().token).toBeNull()
    expect(locationMock.href).toBe('/login')
  })

  it('解析后端 {code,message} 错误体', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ code: 'not_found', message: '资源不存在' }, 404),
    )

    const err: unknown = await apiFetch('/x').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(404)
    expect((err as ApiError).code).toBe('not_found')
    expect((err as ApiError).message).toBe('资源不存在')
  })

  it('POST 请求自动带 JSON Content-Type', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ id: '1' }, 202))

    await apiFetch('/fetch-tasks', { method: 'POST', body: JSON.stringify({ source_key: 'openrouter' }) })

    const [, init] = fetchSpy.mock.calls[0] as unknown as [string, RequestInit]
    expect(new Headers(init.headers).get('Content-Type')).toBe('application/json')
  })
})
