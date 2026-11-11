import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import type { GeneratedAnswer } from '@/api/types'
import { abstained, answered } from '@/test/fixtures'
import { server, serveProvisions } from '@/test/server'
import App from './App'

async function pickRegion(name: string) {
  await userEvent.click(screen.getByRole('combobox', { name: 'Where do you work?' }))
  await userEvent.click(await screen.findByRole('option', { name }))
}

function questionBox() {
  return screen.getByRole('textbox', { name: 'Your question' })
}

function history() {
  return screen.getByRole('navigation', { name: 'Question history' })
}

// Replies with the given answers in turn and counts the requests.
function serveAnswers(...answers: GeneratedAnswer[]) {
  const sent: unknown[] = []
  server.use(
    http.post('/api/ask', async ({ request }) => {
      sent.push(await request.json())
      return HttpResponse.json(answers[Math.min(sent.length, answers.length) - 1])
    }),
  )
  return sent
}

async function ask(text: string, region = 'Sabah') {
  await userEvent.type(questionBox(), text)
  if (screen.getByRole('combobox', { name: 'Where do you work?' }).textContent?.includes('Where do you work?')) {
    await pickRegion(region)
  }
  await userEvent.click(screen.getByRole('button', { name: 'Send' }))
}

test('shows the app name, the empty state and the disclaimer', () => {
  render(<App />)
  expect(screen.getByRole('heading', { name: 'GetRight' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: /What would you like to know/ })).toBeInTheDocument()
  expect(screen.getByText(/legal information, not legal advice/)).toBeInTheDocument()
})

test('Send stays off until there is a question and a region', async () => {
  render(<App />)
  const send = screen.getByRole('button', { name: 'Send' })
  expect(send).toBeDisabled()

  await userEvent.type(questionBox(), 'How many days of annual leave?')
  expect(send).toBeDisabled()

  await pickRegion('Sabah')
  expect(send).toBeEnabled()
})

test('sends the question with the region, shows the answer and adds it to the history', async () => {
  const sent = serveAnswers(answered)
  render(<App />)

  await ask('Annual leave?', 'Peninsular Malaysia and Labuan')

  expect(await screen.findByRole('list', { name: 'Sources' })).toBeInTheDocument()
  expect(sent).toEqual([{ query: 'Annual leave?', region: 'peninsular' }])
  expect(within(history()).getByRole('button', { name: /Annual leave\?/ })).toBeInTheDocument()
  expect(questionBox()).toHaveValue('')
})

test('Enter sends, Shift+Enter starts a new line', async () => {
  const sent = serveAnswers(answered)
  render(<App />)
  await pickRegion('Sarawak')

  await userEvent.type(questionBox(), 'Line one{Shift>}{Enter}{/Shift}line two')
  expect(questionBox()).toHaveValue('Line one\nline two')
  expect(sent).toHaveLength(0)

  await userEvent.type(questionBox(), '{Enter}')
  await screen.findByRole('list', { name: 'Sources' })
  expect(sent).toEqual([{ query: 'Line one\nline two', region: 'sarawak' }])
})

test('a double click sends one request', async () => {
  const sent = serveAnswers(answered)
  render(<App />)

  await userEvent.type(questionBox(), 'Annual leave?')
  await pickRegion('Sarawak')
  await userEvent.dblClick(screen.getByRole('button', { name: 'Send' }))

  await screen.findByRole('list', { name: 'Sources' })
  expect(sent).toHaveLength(1)
})

test('an API error shows its message, and Retry answers the same history entry', async () => {
  let requests = 0
  server.use(
    http.post('/api/ask', () => {
      requests += 1
      return requests === 1
        ? HttpResponse.json({ code: 'generator_unavailable', message: 'The answer service is temporarily unavailable.' }, { status: 503 })
        : HttpResponse.json(answered)
    }),
  )
  render(<App />)

  await ask('Annual leave?')
  expect(await screen.findByRole('alert')).toHaveTextContent('temporarily unavailable')
  await userEvent.click(screen.getByRole('button', { name: 'Retry' }))

  expect(await screen.findByRole('list', { name: 'Sources' })).toBeInTheDocument()
  expect(requests).toBe(2)
  expect(within(history()).getAllByRole('button', { name: /Annual leave\?/ })).toHaveLength(1)
})

test('a second question is a new entry; an old entry opens with its stored answer', async () => {
  serveAnswers(answered, abstained)
  render(<App />)

  await ask('Annual leave?')
  await screen.findByRole('list', { name: 'Sources' })
  await ask('EPF withdrawal?')
  expect(await screen.findByText('Outside what GetRight covers')).toBeInTheDocument()
  expect(screen.queryByText('Annual leave?', { selector: 'p' })).not.toBeInTheDocument()

  await userEvent.click(within(history()).getByRole('button', { name: /Annual leave\?/ }))
  expect(screen.getByRole('list', { name: 'Sources' })).toBeInTheDocument()
})

test('works where scrollTo returns a Promise (recent Chrome and Edge)', async () => {
  const original = Element.prototype.scrollTo
  Element.prototype.scrollTo = () => Promise.resolve() as unknown as void
  try {
    serveAnswers(answered)
    render(<App />)
    await ask('Annual leave?')
    expect(await screen.findByRole('list', { name: 'Sources' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'New question' }))
    expect(screen.getByRole('heading', { name: /What would you like to know/ })).toBeInTheDocument()
  } finally {
    Element.prototype.scrollTo = original
  }
})

test('New question clears the page; history and region survive a reload', async () => {
  serveAnswers(answered)
  const { unmount } = render(<App />)
  await ask('Annual leave?')
  await screen.findByRole('list', { name: 'Sources' })

  await userEvent.click(screen.getByRole('button', { name: 'New question' }))
  expect(screen.getByRole('heading', { name: /What would you like to know/ })).toBeInTheDocument()

  unmount()
  render(<App />)
  expect(within(history()).getByRole('button', { name: /Annual leave\?/ })).toBeInTheDocument()
  expect(screen.getByRole('combobox', { name: 'Where do you work?' })).toHaveTextContent('Sabah')
})

test('the theme button switches between light and dark and remembers the choice', async () => {
  render(<App />)
  const root = document.documentElement
  expect(root).not.toHaveClass('dark') // the test browser reports a light system setting

  await userEvent.click(screen.getByRole('button', { name: 'Switch to dark mode' }))
  expect(root).toHaveClass('dark')
  expect(localStorage.getItem('getright.theme.v1')).toBe('dark')

  await userEvent.click(screen.getByRole('button', { name: 'Switch to light mode' }))
  expect(root).not.toHaveClass('dark')
  expect(localStorage.getItem('getright.theme.v1')).toBe('light')
})


function screenWidth(wide: boolean) {
  const original = window.matchMedia
  window.matchMedia = ((query: string) => ({ ...original(query), matches: wide && query.includes('min-width: 1024px') })) as typeof window.matchMedia
  return () => { window.matchMedia = original }
}

test('on a wide screen a chip opens the source beside the answer, which stays readable', async () => {
  const restore = screenWidth(true)
  try {
    serveAnswers(answered)
    serveProvisions()
    render(<App />)
    await ask('Annual leave?')
    await userEvent.click((await screen.findAllByRole('button', { name: /^Source 1:/ }))[0])

    const aside = screen.getByRole('complementary', { name: 'Source' })
    expect(await within(aside).findByText(/eight days for every twelve months/)).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Answer' })).toBeVisible()
    expect(screen.getAllByText(/./, { selector: 'mark' }).length).toBeGreaterThan(0)

    await userEvent.click(within(aside).getByRole('button', { name: 'Next source' }))
    expect(await within(aside).findByText('Source 2 of 5')).toBeInTheDocument()
    await userEvent.click(within(aside).getByRole('button', { name: 'Close source' }))
    expect(screen.queryByRole('complementary', { name: 'Source' })).not.toBeInTheDocument()
  } finally {
    restore()
  }
})

test('on a narrow screen a chip opens the source as a full-width sheet', async () => {
  serveAnswers(answered)
  serveProvisions()
  render(<App />)
  await ask('Annual leave?')
  await userEvent.click((await screen.findAllByRole('button', { name: /^Source 1:/ }))[0])
  expect(await screen.findByRole('dialog', { name: 'Employment Act 1955, s. 60E(1)' })).toBeInTheDocument()
})
