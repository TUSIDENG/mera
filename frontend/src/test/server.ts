import { setupServer } from 'msw/node'

/** 统一 MSW server：各测试用 server.use() 挂载自己的 handler，保证无真实网络请求 */
export const server = setupServer()
