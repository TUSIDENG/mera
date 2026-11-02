/** 运行时配置：优先 window.MERA_CONFIG（容器内由 /config.js 注入），本地 dev 回落 import.meta.env */

export interface MeraConfig {
  casdoorEndpoint: string
  casdoorClientId: string
}

declare global {
  interface Window {
    MERA_CONFIG?: {
      casdoorEndpoint?: string
      casdoorClientId?: string
    }
  }
}

export function getConfig(): MeraConfig {
  const runtime = window.MERA_CONFIG ?? {}
  return {
    casdoorEndpoint:
      runtime.casdoorEndpoint ||
      import.meta.env.VITE_CASDOOR_ENDPOINT ||
      'http://localhost:8000',
    casdoorClientId:
      runtime.casdoorClientId || import.meta.env.VITE_CASDOOR_CLIENT_ID || '',
  }
}
