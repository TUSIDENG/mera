import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

interface AuthState {
  /** Casdoor access_token */
  token: string | null
  /** 过期时刻（epoch 毫秒），null 表示未知（按已登录处理） */
  expiresAt: number | null
  login: (token: string, expiresIn?: number) => void
  logout: () => void
  isAuthed: () => boolean
}

/** 认证状态：sessionStorage 持久化（键 mera.auth），关标签页即失效 */
export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      expiresAt: null,
      login: (token, expiresIn = 3600) =>
        set({ token, expiresAt: Date.now() + expiresIn * 1000 }),
      logout: () => set({ token: null, expiresAt: null }),
      isAuthed: () => {
        const { token, expiresAt } = get()
        return Boolean(token) && (expiresAt === null || expiresAt > Date.now())
      },
    }),
    { name: 'mera.auth', storage: createJSONStorage(() => sessionStorage) },
  ),
)
