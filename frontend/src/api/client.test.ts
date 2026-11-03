
import { http, HttpResponse } from 'msw'
import { server } from '../test/server'
import { askQuestion } from './client'

describe('askQuestion', () => {
  // Test 1 
  it('sends the question and region, and returns the answer', async () => {
    let sentBody: unknown = null

    server.use(
      http.post('/api/ask', async ({ request }) => {
        sentBody = await request.json()
        return HttpResponse.json({ status: 'answered', answer: 'You get 8 days [1].' })
      }),
    )

    const result = await askQuestion('How many days of annual leave?', 'peninsular')

    expect(sentBody).toEqual({ query: 'How many days of annual leave?', region: 'peninsular' })
    expect(result.status).toBe('answered')
  })
  

  // Test 2 (new)
  it('throws the API message when the backend returns an error', async () => {
    server.use(
      http.post('/api/ask', () =>
        HttpResponse.json(
          { code: 'generator_unavailable', message: 'The answer service is temporarily unavailable.' },
          { status: 503 },
        ),
      ),
    )
    await expect(askQuestion('Any question', 'sabah')).rejects.toThrow('temporarily unavailable')
  })

  // Test 3 (new)
  it('throws a general message when the reply is not JSON', async () => {
    server.use(http.post('/api/ask', () => HttpResponse.text('Bad gateway', { status: 502 })))
    await expect(askQuestion('Any question', 'sabah')).rejects.toThrow('could not reach')
  })

  // Test 4 (new)
  it('throws a general message when the network fails', async () => {
    server.use(http.post('/api/ask', () => HttpResponse.error()))
    await expect(askQuestion('Any question', 'sabah')).rejects.toThrow('could not reach')
  })
}) 