import { AlertTriangle, LogIn } from 'lucide-react'
import { Navigate, useLocation } from 'react-router-dom'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { getConfig } from '../lib/config'
import { buildAuthorizeUrl, pkceChallenge, randomString } from '../lib/oidc'
import { useAuthStore } from '../stores/auth'

/** OIDC 一次性会话参数（state/verifier/登录后回跳地址）的 sessionStorage 键 */
const OIDC_SESSION_KEY = 'mera.oidc'

export default function LoginPage() {
  const isAuthed = useAuthStore((s) => s.isAuthed)
  const location = useLocation()
  const config = getConfig()
  const from = (location.state as { from?: string } | null)?.from

  if (isAuthed()) {
    return <Navigate to="/leaderboard" replace />
  }

  const startLogin = async () => {
    // Casdoor 应用需把 {origin}/callback（如 http://localhost:3000/callback）加入 Redirect URIs
    const state = randomString(16)
    const verifier = randomString(48)
    sessionStorage.setItem(OIDC_SESSION_KEY, JSON.stringify({ state, verifier, from }))
    const challenge = await pkceChallenge(verifier)
    window.location.href = buildAuthorizeUrl({
      endpoint: config.casdoorEndpoint,
      clientId: config.casdoorClientId,
      redirectUri: `${window.location.origin}/callback`,
      state,
      codeChallenge: challenge,
    })
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 px-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl">MERA</CardTitle>
          <CardDescription>大模型评估与选型决策支持系统</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {!config.casdoorClientId && (
            <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                未配置 Casdoor Client ID。请在 .env 设置 CASDOOR_CLIENT_ID 后重启
                frontend-app（本地 dev 设置 VITE_CASDOOR_CLIENT_ID）。
              </span>
            </div>
          )}
          <Button className="w-full" onClick={() => void startLogin()} disabled={!config.casdoorClientId}>
            <LogIn className="h-4 w-4" />
            使用 Casdoor 登录
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
