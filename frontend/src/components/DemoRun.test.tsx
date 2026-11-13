// M6 Task 7: every response from the final real run (scripts/frontend_demo_run.py, 2026-11-13)
// rendered through AnswerView, checking what the user sees in each display state.
import { render, screen, within } from '@testing-library/react'
import type { GeneratedAnswer } from '@/api/types'
import { chipLabel } from '@/lib/citations'
import { AnswerView } from './AnswerView'

const runs = import.meta.glob<GeneratedAnswer>('../test/fixtures/demo/*.json', { eager: true, import: 'default' })
const cases = Object.entries(runs).map(([path, answer]) => [path.split('/').at(-1)!.replace('.json', ''), answer] as const)

test('the final run covers every display state', () => {
  const statuses = new Set(cases.map(([, a]) => a.status))
  expect(statuses).toEqual(new Set(['answered', 'abstained', 'insufficient_context']))
  expect(cases.length).toBe(8)
})

test.each(cases)('%s renders as the user should see it', (_, answer) => {
  render(<AnswerView answer={answer} selected={null} onSelect={() => {}} />)
  const region = screen.getByRole('region', { name: 'Answer' })

  if (answer.status === 'answered') {
    // every citation has a chip with its section reference, and a source card
    for (const citation of answer.citations) {
      expect(screen.getAllByRole('button', { name: `Source ${citation.number}: ${chipLabel(citation)}` }).length).toBeGreaterThan(0)
    }
    expect(within(screen.getByRole('list', { name: 'Sources' })).getAllByRole('listitem')).toHaveLength(answer.citations.length)
    expect(region).not.toHaveTextContent('LIMITS')
    expect(region.textContent).not.toMatch(/\[\d+\]/) // every marker became a chip
  } else {
    expect(screen.getByRole('status')).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'Sources' })).not.toBeInTheDocument()
  }

  const callout = screen.queryByRole('note', { name: 'What the sources cannot tell you' })
  expect(Boolean(callout)).toBe(Boolean(answer.limits))
})
