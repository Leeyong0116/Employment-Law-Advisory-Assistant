import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { GeneratedAnswer } from '@/api/types'
import { abstained, answered, dismissal, insufficient, sarawakMaternity } from '@/test/fixtures'
import { AnswerView } from './AnswerView'

const structured: GeneratedAnswer = {
  ...answered,
  answer: 'You get 8, 12 or 16 days a year [1].\n\n## By length of service\n- Under two years: eight days [1].\n- After a break, unpaid leave over 30 days is not counted [5].',
  limits: 'The sources cannot tell you your own length of service.',
}

function view(answer: GeneratedAnswer, selected: number | null = null) {
  const onSelect = vi.fn()
  render(<AnswerView answer={answer} selected={selected} onSelect={onSelect} />)
  return onSelect
}

test('headings and bullet lists are rendered as such', () => {
  view(structured)
  expect(screen.getByRole('heading', { level: 3, name: 'By length of service' })).toBeInTheDocument()
  const list = screen.getByRole('list', { name: '' })
  expect(within(list).getAllByRole('listitem')).toHaveLength(2)
})

test('a chip names the section for hover and screen readers, and sits after the full stop', () => {
  view(structured)
  const chip = screen.getAllByRole('button', { name: 'Source 1: s. 60E(1), Employment Act 1955' })[0]
  expect(chip).toHaveAttribute('title', 's. 60E(1), Employment Act 1955')
  expect(chip.parentElement).toHaveTextContent(/^You get 8, 12 or 16 days a year\.1$/)
})

test('clicking a chip or a source card selects that citation', async () => {
  const onSelect = view(structured)
  await userEvent.click(screen.getAllByRole('button', { name: /^Source 5:/ })[0])
  expect(onSelect).toHaveBeenLastCalledWith(5)
  const sources = screen.getByRole('list', { name: 'Sources' })
  await userEvent.click(within(sources).getByRole('button', { name: /s\. 60E\(1\)/ }))
  expect(onSelect).toHaveBeenLastCalledWith(1)
})

test('the selected citation highlights its sentence and its source card', () => {
  view(structured, 5)
  const marked = screen.getAllByText(/unpaid leave over 30 days/, { selector: 'mark' })
  expect(marked).toHaveLength(1)
  expect(screen.queryByText(/eight days/, { selector: 'mark' })).not.toBeInTheDocument()
  const card = within(screen.getByRole('list', { name: 'Sources' })).getByRole('button', { name: /s\. 60E\(3B\)/ })
  expect(card).toHaveAttribute('aria-pressed', 'true')
})

test('the limits are a callout under the answer, not part of its text', () => {
  view(structured)
  const callout = screen.getByRole('note', { name: 'What the sources cannot tell you' })
  expect(callout).toHaveTextContent('The sources cannot tell you your own length of service.')
  expect(screen.getByRole('region', { name: 'Answer' })).toHaveTextContent(/16 days a year/)
})

test('source cards show no jurisdiction line', () => {
  view(structured)
  const sources = screen.getByRole('list', { name: 'Sources' })
  expect(within(sources).queryByText('Peninsular Malaysia and Labuan')).not.toBeInTheDocument()
})

test('a marker with no matching citation stays plain text', () => {
  view({ ...answered, answer: 'Eight days [1]. Something else [9].' })
  expect(screen.queryByRole('button', { name: /Source 9/ })).not.toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'Answer' })).toHaveTextContent('Something else [9].')
})

test('a gate abstention is a notice listing the statutes held, with no Sources', () => {
  view(abstained)
  const notice = screen.getByRole('status')
  expect(notice).toHaveTextContent('Industrial Relations Act 1967 (Act 177), Malaysia')
  expect(notice).toHaveTextContent('Department of Labour')
  expect(screen.queryByRole('list', { name: 'Sources' })).not.toBeInTheDocument()
})

test('a model refusal (insufficient context) is a notice, not an empty answer', () => {
  view(insufficient)
  expect(screen.getByRole('status')).toHaveTextContent('do not answer this question')
})

test('notes, external dependencies and non-current sources are shown', () => {
  view({
    ...sarawakMaternity,
    external_dependencies: ["Workmen's Compensation Act 1952 [Act 273]"],
    citations: [{ ...sarawakMaternity.citations[0], status: 'superseded' }],
  })
  expect(screen.getByText(/substituted "worker" with "employee"/)).toBeInTheDocument()
  expect(screen.getByText(/Workmen's Compensation Act 1952 \[Act 273\], which GetRight does not hold/)).toBeInTheDocument()
  expect(within(screen.getByRole('list', { name: 'Sources' })).getByText('Amended later')).toBeInTheDocument()
})


test('a real m4-v3 answer renders as headings, lists and a limits callout', () => {
  view(dismissal)
  const answer = screen.getByRole('region', { name: 'Answer' })
  expect(within(answer).getAllByRole('heading', { level: 3 })).toHaveLength(2)
  expect(answer.querySelectorAll('ul > li')).toHaveLength(5) // bullets only; the Sources list is an ol
  expect(answer).not.toHaveTextContent('LIMITS')
  expect(answer.textContent).not.toMatch(/\s\./) // no gap before a full stop
  expect(screen.getByRole('note', { name: 'What the sources cannot tell you' })).toHaveTextContent('due inquiry was held')
})
