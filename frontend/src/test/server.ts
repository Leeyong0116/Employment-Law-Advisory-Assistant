import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { provisions } from './fixtures'

// Each test adds its own handlers with server.use(...).
export const server = setupServer()

// Serves the provision fixtures; an unknown id gets the API's real 404 body.
export function serveProvisions() {
  server.use(
    http.get('/api/provisions/:chunkId', ({ params }) => {
      const provision = provisions[params.chunkId as string]
      return provision
        ? HttpResponse.json(provision)
        : HttpResponse.json({ code: 'not_found', message: 'No provision with this id in the corpus.' }, { status: 404 })
    }),
  )
}
