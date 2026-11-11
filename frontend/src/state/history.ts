// Question history, kept in this browser only (CLAUDE.md, Privacy and ethics: no
// server-side conversation storage). One question per entry: the API answers each
// question on its own, so there are no follow-ups (plan D2).
// Storage can be missing, full or blocked (private window); then the app still works
// and history is simply not kept.
import type { GeneratedAnswer, Region } from '@/api/types'

export const HISTORY_KEY = 'getright.history.v1' // a new format gets a new key, so old data is never misread
export const REGION_KEY = 'getright.region.v1'
export const MAX_ENTRIES = 50

export type HistoryEntry = {
  id: string
  query: string
  region: Region
  createdAt: string
  answer?: GeneratedAnswer // stored exactly as the API returned it
  error?: string
}

const REGIONS: readonly string[] = ['peninsular', 'sabah', 'sarawak']

function isEntry(value: unknown): value is HistoryEntry {
  if (typeof value !== 'object' || value === null) return false
  const e = value as Record<string, unknown>
  return typeof e.id === 'string' && typeof e.query === 'string' && typeof e.createdAt === 'string'
    && typeof e.region === 'string' && REGIONS.includes(e.region)
}

/** Entries newest first. Malformed entries are dropped. */
export function loadHistory(): HistoryEntry[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(HISTORY_KEY) ?? '[]')
    return Array.isArray(parsed) ? parsed.filter(isEntry).slice(0, MAX_ENTRIES) : []
  } catch {
    return []
  }
}

/** Saves newest first. If storage is full, keeps fewer (the newest) until it fits. */
export function saveHistory(entries: HistoryEntry[]): void {
  let kept = entries.slice(0, MAX_ENTRIES)
  while (kept.length > 0) {
    try {
      localStorage.setItem(HISTORY_KEY, JSON.stringify(kept))
      return
    } catch {
      kept = kept.slice(0, Math.floor(kept.length / 2))
    }
  }
}

export function loadRegion(): Region | null {
  try {
    const value = localStorage.getItem(REGION_KEY)
    return value !== null && REGIONS.includes(value) ? (value as Region) : null
  } catch {
    return null
  }
}

export function saveRegion(region: Region): void {
  try {
    localStorage.setItem(REGION_KEY, region)
  } catch {
    // storage blocked: the choice is just not remembered
  }
}
