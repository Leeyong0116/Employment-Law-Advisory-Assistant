import { useCallback, useEffect, useRef, useState } from 'react'
import { Scale } from 'lucide-react'
import { askQuestion } from '@/api/client'
import type { Region } from '@/api/types'
import { AnswerView } from '@/components/AnswerView'
import { AppSidebar } from '@/components/AppSidebar'
import { Composer } from '@/components/Composer'
import { SourcePanel } from '@/components/SourcePanel'
import { Button } from '@/components/ui/button'
import { ThemeToggle } from '@/components/ThemeToggle'
import { SidebarInset, SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'
import { useMediaQuery } from '@/hooks/use-media-query'
import { regionLabel } from '@/lib/regions'
import { MAX_ENTRIES, loadHistory, loadRegion, saveHistory, saveRegion, type HistoryEntry } from '@/state/history'

// Layout like a chat app: history on the left, the question and answer in the middle,
// the question box pinned at the bottom. Each question is its own entry (plan D2):
// sending always starts a new entry, so two questions never look like one conversation.
export default function App() {
  const [entries, setEntries] = useState<HistoryEntry[]>(loadHistory)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [question, setQuestion] = useState('')
  const [region, setRegion] = useState<Region | null>(loadRegion) // remembered, never defaulted (plan D3)
  const [pendingId, setPendingId] = useState<string | null>(null)
  const [selected, setSelected] = useState<number | null>(null) // citation open in the source panel
  const wide = useMediaQuery('(min-width: 1024px)') // room for the source panel beside the answer
  const inFlight = useRef(false) // blocks a second request before React re-renders the disabled button
  const scrollRef = useRef<HTMLDivElement>(null)

  const active = entries.find((e) => e.id === activeId) ?? null
  const canSend = question.trim().length > 0 && region !== null && pendingId === null

  // Keep localStorage in step with the entries (an effect: it syncs with something outside React).
  // Effects use { } bodies: an effect may return only a cleanup function. In recent
  // Chrome and Edge, scrollTo returns a Promise, so `() => el.scrollTo(...)` crashed the page.
  useEffect(() => {
    saveHistory(entries)
  }, [entries])

  // A newly opened entry starts at the top.
  useEffect(() => {
    scrollRef.current?.scrollTo?.({ top: 0 })
  }, [activeId])

  function openEntry(id: string | null) {
    setActiveId(id)
    setSelected(null)
  }

  const closeSource = useCallback(() => setSelected(null), [])
  const sourceOpen = selected !== null && Boolean(active?.answer?.citations.length)

  function updateEntry(id: string, change: Partial<HistoryEntry>) {
    setEntries((prev) => prev.map((e) => (e.id === id ? { ...e, ...change } : e)))
  }

  async function run(entry: HistoryEntry) {
    if (inFlight.current) return
    inFlight.current = true
    setPendingId(entry.id)
    updateEntry(entry.id, { answer: undefined, error: undefined })
    try {
      updateEntry(entry.id, { answer: await askQuestion(entry.query, entry.region) })
    } catch (err) {
      updateEntry(entry.id, { error: err instanceof Error ? err.message : 'Something went wrong.' })
    } finally {
      inFlight.current = false
      setPendingId(null)
    }
  }

  function handleSend() {
    if (inFlight.current || !canSend || !region) return
    const entry: HistoryEntry = {
      id: crypto.randomUUID(),
      query: question.trim(),
      region,
      createdAt: new Date().toISOString(),
    }
    setEntries((prev) => [entry, ...prev].slice(0, MAX_ENTRIES))
    openEntry(entry.id)
    setQuestion('')
    run(entry)
  }

  function handleRegionChange(value: Region) {
    setRegion(value)
    saveRegion(value)
  }

  return (
    <SidebarProvider>
      <AppSidebar entries={entries} activeId={activeId} onSelect={openEntry} onNew={() => openEntry(null)} />

      <SidebarInset className="h-svh overflow-hidden">
        <header className="flex h-12 shrink-0 items-center gap-2 px-3">
          <SidebarTrigger />
          <h1 className="text-base font-semibold tracking-tight">GetRight</h1>
          <div className="ml-auto">
            <ThemeToggle />
          </div>
        </header>

        <div className="flex min-h-0 flex-1">
          <div className="flex min-w-0 flex-1 flex-col">
            {/* min-h-0 lets this column scroll inside the page instead of growing under the question box */}
            <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
              <div className="mx-auto w-full max-w-3xl px-4 pb-16 pt-4">
                {active ? (
                  <Turn
                    entry={active}
                    pending={pendingId === active.id}
                    onRetry={() => run(active)}
                    selected={selected}
                    onSelect={setSelected}
                  />
                ) : (
                  <EmptyState />
                )}
              </div>
            </div>

            <div className="shrink-0 bg-background px-4 pb-3 pt-1">
              <div className="mx-auto w-full max-w-3xl">
                <Composer
                  question={question}
                  onQuestionChange={setQuestion}
                  region={region}
                  onRegionChange={handleRegionChange}
                  canSend={canSend}
                  onSend={handleSend}
                />
              </div>
            </div>
          </div>

          {sourceOpen && active?.answer && (
            <SourcePanel
              citations={active.answer.citations}
              selected={selected!}
              onSelect={setSelected}
              onClose={closeSource}
              layout={wide ? 'side' : 'sheet'}
            />
          )}
        </div>
      </SidebarInset>
    </SidebarProvider>
  )
}

function EmptyState() {
  return (
    <div className="flex min-h-[50svh] flex-col items-center justify-center gap-3 text-center">
      <Scale className="size-8 text-muted-foreground" aria-hidden />
      <h2 className="text-2xl font-semibold tracking-tight">What would you like to know about your employment rights?</h2>
      <p className="max-w-md text-sm leading-6 text-muted-foreground">
        Choose where you work, so GetRight answers from the law that applies there. Every answer shows the
        provisions it was taken from.
      </p>
    </div>
  )
}

type TurnProps = {
  entry: HistoryEntry
  pending: boolean
  onRetry: () => void
  selected: number | null
  onSelect: (number: number) => void
}

// One question and its answer: the question on the right, the answer below it.
function Turn({ entry, pending, onRetry, selected, onSelect }: TurnProps) {
  const interrupted = !pending && !entry.answer && !entry.error // the page closed before the answer came

  return (
    <div className="space-y-8">
      <div className="ml-auto w-fit max-w-[85%] space-y-1 rounded-3xl bg-muted px-5 py-3">
        <p className="whitespace-pre-wrap text-[15px] leading-7">{entry.query}</p>
        <p className="text-xs text-muted-foreground">{regionLabel(entry.region)}</p>
      </div>

      <div className="flex gap-4">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-full border" aria-hidden>
          <Scale className="size-4" />
        </div>
        <div className="min-w-0 flex-1 pt-1">
          <div aria-live="polite">
            {pending && (
              <p className="animate-pulse text-sm text-muted-foreground">Searching the statutes and writing the answer...</p>
            )}
          </div>

          {entry.error && (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-destructive/30 bg-destructive/10 p-4">
              <p role="alert" className="text-sm text-destructive">{entry.error}</p>
              <Button variant="outline" size="sm" onClick={onRetry}>Retry</Button>
            </div>
          )}

          {interrupted && (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-muted/40 p-4 text-sm">
              <p>This question did not get an answer: the page was closed or reloaded before it finished.</p>
              <Button variant="outline" size="sm" onClick={onRetry}>Ask again</Button>
            </div>
          )}

          {entry.answer && <AnswerView answer={entry.answer} selected={selected} onSelect={onSelect} />}
        </div>
      </div>
    </div>
  )
}
