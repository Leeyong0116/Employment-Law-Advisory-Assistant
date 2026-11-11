import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Citation } from '@/api/types'
import { answered } from '@/test/fixtures'
import { serveProvisions } from '@/test/server'
import { SourcePanel } from './SourcePanel'

const annualLeave = answered.citations[0] // [1] EA1955_s60E_1

function citationTo(chunkId: string, label: string): Citation {
  return { ...annualLeave, chunk_id: chunkId, citation: label }
}

function panel(citations: Citation[], selected = 1, layout: 'side' | 'sheet' = 'side') {
  const onSelect = vi.fn()
  const onClose = vi.fn()
  render(<SourcePanel citations={citations} selected={selected} onSelect={onSelect} onClose={onClose} layout={layout} />)
  return { onSelect, onClose }
}

beforeEach(() => serveProvisions())

test('beside the answer it is a panel, not a modal dialog', async () => {
  panel([annualLeave])
  expect(screen.getByRole('complementary', { name: 'Source' })).toBeInTheDocument()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(await screen.findByRole('heading', { name: 'Employment Act 1955, s. 60E(1)' })).toBeInTheDocument()
})

test('on narrow screens it is a full-width sheet', async () => {
  panel([annualLeave], 1, 'sheet')
  expect(await screen.findByRole('dialog', { name: 'Employment Act 1955, s. 60E(1)' })).toBeInTheDocument()
})

test('shows the provision text, its source details and the traceability note', async () => {
  panel([annualLeave])
  const aside = screen.getByRole('complementary', { name: 'Source' })
  expect(await screen.findByText(/eight days for every twelve months/)).toBeInTheDocument()
  expect(aside).toHaveTextContent('as at 1 January 2023')
  expect(aside).toHaveTextContent('pages 63 to 64')
  expect(screen.getByRole('link', { name: /official source/ })).toHaveAttribute('href', 'https://lom.agc.gov.my/')
  expect(aside).toHaveTextContent('GetRight does not check that it legally supports the statement')
})

test('previous and next step through the sources; close and Escape close it', async () => {
  const { onSelect, onClose } = panel(answered.citations, 2)
  expect(screen.getByText('Source 2 of 5')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Next source' }))
  expect(onSelect).toHaveBeenLastCalledWith(3)
  await userEvent.click(screen.getByRole('button', { name: 'Previous source' }))
  expect(onSelect).toHaveBeenLastCalledWith(1)
  await userEvent.click(screen.getByRole('button', { name: 'Close source' }))
  await userEvent.keyboard('{Escape}')
  expect(onClose).toHaveBeenCalledTimes(2)
})

test('previous is off on the first source and next on the last', () => {
  panel(answered.citations, 1)
  expect(screen.getByRole('button', { name: 'Previous source' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Next source' })).toBeEnabled()
})

test('a superseded provision says so and opens its amendment', async () => {
  panel([citationTo('SWK76_s84_1', 'Labour Ordinance (Sarawak), s. 84(1)')])
  expect(await screen.findByText(/A later amendment changed this provision/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /A1754_s24/ }))
  expect(await screen.findByRole('heading', { name: 'Labour Ordinance of Sarawak (Amendment) Act 2025, s. 24' })).toBeInTheDocument()
  expect(await screen.findByText(/In force from 2025-05-01/)).toBeInTheDocument()
})

test('a deleted provision shows what deleted it and the note from the source', async () => {
  panel([citationTo('EA1955_s9', 'Employment Act 1955, s. 9')])
  expect(await screen.findByText('Deleted by Act 40 of 1966. This is not current law.')).toBeInTheDocument()
  expect(screen.getByText(/has since been revised as the Children and Young Persons/)).toBeInTheDocument()
})

test('a provision missing from the corpus keeps the stored label and explains', async () => {
  panel([citationTo('GONE_s1', 'Employment Act 1955, s. 99')])
  expect(await screen.findByRole('alert')).toHaveTextContent('No provision with this id in the corpus.')
  expect(screen.getByRole('heading', { name: 'Employment Act 1955, s. 99' })).toBeInTheDocument()
})
