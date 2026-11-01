import { setupServer } from 'msw/node'

// Each test adds its own handlers with server.use(...).
export const server = setupServer()
