import { answered } from '@/test/fixtures'
import { HISTORY_KEY, MAX_ENTRIES, loadHistory, loadRegion, saveHistory, saveRegion, type HistoryEntry } from './history'

function entry(n: number): HistoryEntry {
  return { id: `id-${n}`, query: `question ${n}`, region: 'sabah', createdAt: '2026-11-11T10:00:00.000Z' }
}

afterEach(() => vi.restoreAllMocks())

test('saves and loads entries, answer kept exactly as received', () => {
  saveHistory([{ ...entry(1), answer: answered }])
  expect(loadHistory()).toEqual([{ ...entry(1), answer: answered }])
})

test('keeps at most 50 entries, dropping the oldest (the end of the list)', () => {
  saveHistory(Array.from({ length: 60 }, (_, n) => entry(n)))
  const loaded = loadHistory()
  expect(loaded).toHaveLength(MAX_ENTRIES)
  expect(loaded[0].id).toBe('id-0')
  expect(loaded.at(-1)?.id).toBe('id-49')
})

test('drops malformed or older-format entries instead of crashing', () => {
  localStorage.setItem(HISTORY_KEY, JSON.stringify([entry(1), { id: 2, text: 'old format' }, null, { ...entry(3), region: 'mars' }]))
  expect(loadHistory().map((e) => e.id)).toEqual(['id-1'])

  localStorage.setItem(HISTORY_KEY, '{not json')
  expect(loadHistory()).toEqual([])
})

test('works when storage throws (private window or blocked site data)', () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
  expect(() => saveHistory([entry(1)])).not.toThrow()
  expect(loadHistory()).toEqual([])
  expect(() => saveRegion('sarawak')).not.toThrow()
  expect(loadRegion()).toBeNull()
})

test('when storage is full, keeps the newest entries that fit', () => {
  const realSetItem = Storage.prototype.setItem
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, key: string, value: string) {
    if (value.length > 400) throw new DOMException('full', 'QuotaExceededError')
    realSetItem.call(this, key, value)
  })
  saveHistory(Array.from({ length: 10 }, (_, n) => entry(n)))
  const loaded = loadHistory()
  expect(loaded.length).toBeGreaterThan(0)
  expect(loaded.length).toBeLessThan(10)
  expect(loaded[0].id).toBe('id-0')
})

test('remembers the region, and ignores an unknown value', () => {
  expect(loadRegion()).toBeNull()
  saveRegion('sarawak')
  expect(loadRegion()).toBe('sarawak')
  localStorage.setItem('getright.region.v1', 'mars')
  expect(loadRegion()).toBeNull()
})
