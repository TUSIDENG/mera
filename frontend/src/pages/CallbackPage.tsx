import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Skeleton } from '../components/ui/skeleton'
import { getConfig } from '../lib/config'
import { exchangeCode } from '../lib/oidc'
import { useAuthStore } from '../stores/auth'

const OIDC_SESSION_KEY = 'mera.oidc'

interface OidcSession {
  state: string
  verifier: string
  from?: string
}

/** OIDC 回调：校验 state、用 code + code_verifier 换 token，成功跳回登录前目标页 */
export default function CallbackPage() {
  const navigate = useNavigate()
  const login = useAuthStore((s) => s.login)
  const [error, setError] = useState<string | null>(null)
  // StrictMode 下 effect 会执行两次，code 只能换一次 token，加一次性守卫
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return
    started.current = true

    const run = async () => {
      const params = new URLSearchParams(window.location.search)
      const code = params.get('code')
      const state = params.get('state')
      const savedRaw = sessionStorage.getItem(OIDC_SESSION_KEY)
      // state/verifier 一次性使用，无论成败立即清除
      sessionStorage.removeItem(OIDC_SESSION_KEY)
      if (!code || !state || !savedRaw) {
        throw new Error('登录会话无效或已过期，请重新登录')
      }
      const saved = JSON.parse(savedRaw) as OidcSession
      if (state !== saved.state) {
        throw new Error('state 校验失败，可能存在 CSRF 风险，请重新登录')
      }
      const config = getConfig()
      const token = await exchangeCode({
        endpoint: config.casdoorEndpoint,
        clientId: config.casdoorClientId,
        code,
        redirectUri: `${window.location.origin}/callback`,
        codeVerifier: saved.verifier,
      })
      login(token.access_token, token.expires_in ?? 3600)
      const target = saved.from && saved.from !== '/login' ? saved.from : '/leaderboard'
      navigate(target, { replace: true })
    }

    run().catch((e: unknown) => setError(e instanceof Error ? e.message : '登录失败'))
  }, [login, navigate])

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 px-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <CardTitle>{error ? '登录失败' : '正在完成登录'}</CardTitle>
          <CardDescription>{error ? '请重试或联系管理员' : '正在与 Casdoor 交换令牌…'}</CardDescription>
        </CardHeader>
        <CardContent>
          {error ? (
            <div className="space-y-4">
              <p className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>
              <Button className="w-full" onClick={() => navigate('/login', { replace: true })}>
                返回登录
              </Button>
            </div>
          ) : (
            <div className="space-y-2">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
