/** Casdoor OIDC Authorization Code + PKCE 工具函数（纯前端实现，不依赖 SDK） */

/** base64url 编码（去掉 padding，+ / 替换为 - _） */
export function base64url(bytes: Uint8Array): string {
  let binary = ''
  for (const b of bytes) binary += String.fromCharCode(b)
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

/** 生成 URL-safe 随机串（state / code_verifier 用） */
export function randomString(byteLength = 32): string {
  const bytes = new Uint8Array(byteLength)
  crypto.getRandomValues(bytes)
  return base64url(bytes)
}

/** SHA-256 摘要 */
export async function sha256(input: string): Promise<ArrayBuffer> {
  const data = new TextEncoder().encode(input)
  return crypto.subtle.digest('SHA-256', data)
}

/** PKCE code_challenge = base64url(S256(code_verifier)) */
export async function pkceChallenge(verifier: string): Promise<string> {
  return base64url(new Uint8Array(await sha256(verifier)))
}

export interface AuthorizeParams {
  endpoint: string
  clientId: string
  redirectUri: string
  state: string
  codeChallenge: string
}

/** 拼接 Casdoor 授权跳转 URL */
export function buildAuthorizeUrl(params: AuthorizeParams): string {
  const url = new URL('/login/oauth/authorize', params.endpoint)
  url.searchParams.set('response_type', 'code')
  url.searchParams.set('client_id', params.clientId)
  url.searchParams.set('redirect_uri', params.redirectUri)
  url.searchParams.set('scope', 'openid profile email')
  url.searchParams.set('state', params.state)
  url.searchParams.set('code_challenge', params.codeChallenge)
  url.searchParams.set('code_challenge_method', 'S256')
  return url.toString()
}

export interface TokenResponse {
  access_token: string
  expires_in?: number
  token_type?: string
  id_token?: string
  refresh_token?: string
}

export interface ExchangeParams {
  endpoint: string
  clientId: string
  code: string
  redirectUri: string
  codeVerifier: string
}

/** 回调阶段：用 authorization code + code_verifier 换 access_token */
export async function exchangeCode(params: ExchangeParams): Promise<TokenResponse> {
  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    client_id: params.clientId,
    code: params.code,
    redirect_uri: params.redirectUri,
    code_verifier: params.codeVerifier,
  })
  const res = await fetch(`${params.endpoint}/api/login/oauth/access_token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })
  if (!res.ok) {
    throw new Error(`换取访问令牌失败（HTTP ${res.status}）`)
  }
  const data = (await res.json()) as TokenResponse
  if (!data.access_token) {
    throw new Error('令牌响应缺少 access_token')
  }
  return data
}
