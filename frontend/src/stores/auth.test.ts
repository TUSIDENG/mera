import { beforeEach, describe, expect, it } from 'vitest'
import { useAuthStore } from './auth'

describe('auth store', () => {
  beforeEach(() => {
    useAuthStore.getState().logout()
    window.sessionStorage.clear()
  })

  it('login 写入 token 与过期时刻，isAuthed 为 true', () => {
    useAuthStore.getState().login('token-1', 3600)
    const state = useAuthStore.getState()
    expect(state.token).toBe('token-1')
    expect(state.expiresAt).toBeGreaterThan(Date.now())
    expect(state.isAuthed()).toBe(true)
  })

  it('login 持久化到 sessionStorage（键 mera.auth）', () => {
    useAuthStore.getState().login('token-persist', 3600)
    const raw = window.sessionStorage.getItem('mera.auth')
    expect(raw).toBeTruthy()
    expect(JSON.parse(raw!).state.token).toBe('token-persist')
  })

  it('logout 清空登录态', () => {
    useAuthStore.getState().login('token-1', 3600)
    useAuthStore.getState().logout()
    expect(useAuthStore.getState().token).toBeNull()
    expect(useAuthStore.getState().isAuthed()).toBe(false)
  })

  it('token 过期后 isAuthed 为 false', () => {
    // expiresIn 为负，立即过期
    useAuthStore.getState().login('token-expired', -10)
    expect(useAuthStore.getState().isAuthed()).toBe(false)
  })
})
