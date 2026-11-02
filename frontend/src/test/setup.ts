import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { webcrypto } from 'node:crypto'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { server } from './server'

// jsdom 未实现完整 WebCrypto，注入 Node 的 webcrypto（PKCE sha256 依赖）
if (!globalThis.crypto?.subtle) {
  Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true })
}

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))

afterEach(() => {
  cleanup()
  server.resetHandlers()
  window.sessionStorage.clear()
})

afterAll(() => server.close())
