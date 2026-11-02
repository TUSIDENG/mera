import { describe, expect, it, vi } from 'vitest'
import { base64url, buildAuthorizeUrl, exchangeCode, pkceChallenge, randomString } from './oidc'

describe('oidc 纯函数', () => {
  it('base64url 无 padding 且字符 URL-safe', () => {
    // 0xFB 0xFF 0xBE → base64 "+/++"，base64url 应替换 + / 为 - _
    expect(base64url(new Uint8Array([251, 255, 190]))).toBe('-_--')
    // 单字节触发 padding，应去掉 =
    expect(base64url(new Uint8Array([251]))).toBe('-w')
    expect(base64url(new Uint8Array([1, 2, 3]))).toMatch(/^[A-Za-z0-9_-]+$/)
  })

  it('randomString 生成 URL-safe 随机串', () => {
    const a = randomString(32)
    const b = randomString(32)
    expect(a).toMatch(/^[A-Za-z0-9_-]+$/)
    expect(a).not.toBe(b)
  })

  it('pkceChallenge 确定性：S256("abc") 符合 RFC 7636 已知值', async () => {
    // sha256("abc") 的 base64url 编码（已知测试向量）
    await expect(pkceChallenge('abc')).resolves.toBe('ungWv48Bz-pBQUDeXa4iI7ADYaOWF3qctBD_YfIAFa0')
  })

  it('buildAuthorizeUrl 参数齐全', () => {
    const url = new URL(
      buildAuthorizeUrl({
        endpoint: 'http://localhost:8000',
        clientId: 'cid',
        redirectUri: 'http://localhost:3000/callback',
        state: 'st',
        codeChallenge: 'ch',
      }),
    )
    expect(url.origin).toBe('http://localhost:8000')
    expect(url.pathname).toBe('/login/oauth/authorize')
    expect(url.searchParams.get('response_type')).toBe('code')
    expect(url.searchParams.get('client_id')).toBe('cid')
    expect(url.searchParams.get('redirect_uri')).toBe('http://localhost:3000/callback')
    expect(url.searchParams.get('scope')).toBe('openid profile email')
    expect(url.searchParams.get('state')).toBe('st')
    expect(url.searchParams.get('code_challenge')).toBe('ch')
    expect(url.searchParams.get('code_challenge_method')).toBe('S256')
  })

  it('exchangeCode 发送正确的 form-urlencoded 请求体并解析 token', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ access_token: 'at-1', expires_in: 7200 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    const token = await exchangeCode({
      endpoint: 'http://localhost:8000',
      clientId: 'cid',
      code: 'code-1',
      redirectUri: 'http://localhost:3000/callback',
      codeVerifier: 'verifier-1',
    })

    expect(token.access_token).toBe('at-1')
    expect(token.expires_in).toBe(7200)

    const [url, init] = fetchSpy.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('http://localhost:8000/api/login/oauth/access_token')
    expect(init.method).toBe('POST')
    expect(new Headers(init.headers).get('Content-Type')).toBe('application/x-www-form-urlencoded')
    const body = new URLSearchParams(init.body as string)
    expect(body.get('grant_type')).toBe('authorization_code')
    expect(body.get('client_id')).toBe('cid')
    expect(body.get('code')).toBe('code-1')
    expect(body.get('redirect_uri')).toBe('http://localhost:3000/callback')
    expect(body.get('code_verifier')).toBe('verifier-1')

    fetchSpy.mockRestore()
  })

  it('exchangeCode 对非 2xx 抛错', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response('bad', { status: 400 }))
    await expect(
      exchangeCode({
        endpoint: 'http://localhost:8000',
        clientId: 'cid',
        code: 'x',
        redirectUri: 'http://localhost:3000/callback',
        codeVerifier: 'y',
      }),
    ).rejects.toThrow('HTTP 400')
    fetchSpy.mockRestore()
  })
})
