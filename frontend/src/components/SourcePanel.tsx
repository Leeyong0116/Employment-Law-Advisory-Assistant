import { useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, ExternalLink, TriangleAlert, X } from 'lucide-react'
import { getProvision } from '@/api/client'
import type { Citation, Provision } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'

type Layout = 'side' | 'sheet'

type SourcePanelProps = {
  citations: Citation[] // the answer's citations, in number order
  selected: number
  onSelect: (number: number) => void
  onClose: () => void
  layout: Layout // 'side': a column beside the answer (wide screens); 'sheet': full-width overlay (narrow)
}

// The source of one citation, with previous / next through the answer's citations.
// Beside the answer it is a plain column, so the answer stays readable; on a narrow
// screen there is no room beside it, so it becomes a sheet over the page.
export function SourcePanel({ citations, selected, onSelect, onClose, layout }: SourcePanelProps) {
  const index = citations.findIndex((c) => c.number === selected)
  const citation = citations[index]

  // Escape closes the side panel (the sheet handles Escape itself).
  useEffect(() => {
    if (layout !== 'side') return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [layout, onClose])

  if (!citation) return null
  const view = (
    <SourceView
      key={citation.chunk_id} // a new citation starts fresh, so an old text never shows under a new heading
      citation={citation}
      position={`Source ${index + 1} of ${citations.length}`}
      onPrevious={index > 0 ? () => onSelect(citations[index - 1].number) : undefined}
      onNext={index < citations.length - 1 ? () => onSelect(citations[index + 1].number) : undefined}
      onClose={onClose}
      layout={layout}
    />
  )

  if (layout === 'sheet') {
    return (
      <Sheet open onOpenChange={onClose}>
        <SheetContent showCloseButton={false} className="w-full gap-0 sm:max-w-full">
          {view}
        </SheetContent>
      </Sheet>
    )
  }
  return (
    <aside aria-label="Source" className="flex h-full w-[min(440px,42vw)] shrink-0 flex-col border-l bg-background">
      {view}
    </aside>
  )
}

type SourceViewProps = {
  citation: Citation
  position: string
  onPrevious?: () => void
  onNext?: () => void
  onClose: () => void
  layout: Layout
}

// One citation's source. Starts at the cited chunk; an amendment link moves to another chunk.
function SourceView({ citation, position, onPrevious, onNext, onClose, layout }: SourceViewProps) {
  const [chunkId, setChunkId] = useState(citation.chunk_id)
  const label = chunkId === citation.chunk_id ? citation.citation : chunkId

  return (
    <>
      <div className="flex h-12 shrink-0 items-center gap-1 border-b px-3">
        <span className="text-xs font-medium text-muted-foreground">{position}</span>
        <div className="ml-auto flex items-center gap-1">
          <Button variant="ghost" size="icon-sm" aria-label="Previous source" disabled={!onPrevious} onClick={onPrevious}>
            <ChevronLeft aria-hidden />
          </Button>
          <Button variant="ghost" size="icon-sm" aria-label="Next source" disabled={!onNext} onClick={onNext}>
            <ChevronRight aria-hidden />
          </Button>
          <Button variant="ghost" size="icon-sm" aria-label="Close source" onClick={onClose}>
            <X aria-hidden />
          </Button>
        </div>
      </div>
      <ProvisionView key={chunkId} chunkId={chunkId} fallbackLabel={label} onOpen={setChunkId} layout={layout} />
    </>
  )
}

type ProvisionViewProps = {
  chunkId: string
  fallbackLabel: string
  onOpen: (chunkId: string) => void
  layout: Layout
}

function ProvisionView({ chunkId, fallbackLabel, onOpen, layout }: ProvisionViewProps) {
  const [provision, setProvision] = useState<Provision | null>(null)
  const [error, setError] = useState<string | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    getProvision(chunkId)
      .then(setProvision)
      .catch((err) => setError(err instanceof Error ? err.message : 'Could not load this provision.'))
  }, [chunkId])

  // Beside the answer, move keyboard focus to the newly opened source.
  useEffect(() => {
    if (layout === 'side') heading.current?.focus({ preventScroll: true })
  }, [chunkId, layout])

  // The heading comes from API fields only (core contribution 1).
  const title = provision?.citation ?? fallbackLabel
  const description = provision ? describe(provision) : 'Source provision'

  return (
    <div className="flex-1 space-y-5 overflow-y-auto p-4">
      <div className="space-y-1">
        {layout === 'sheet' ? (
          <>
            <SheetTitle className="text-base leading-snug">{title}</SheetTitle>
            <SheetDescription>{description}</SheetDescription>
          </>
        ) : (
          <>
            <h2 ref={heading} tabIndex={-1} className="text-base font-semibold leading-snug outline-none">{title}</h2>
            <p className="text-sm text-muted-foreground">{description}</p>
          </>
        )}
      </div>

      {error && (
        <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          {error} The index may have changed since this answer was written.
        </p>
      )}

      {!provision && !error && (
        <p aria-live="polite" className="text-sm text-muted-foreground">Loading the provision...</p>
      )}

      {provision && (
        <>
          <StatusBanner provision={provision} onOpen={onOpen} />

          {/* pre-wrap keeps the line breaks, so provisos and (a), (b) items stay readable */}
          <p className="whitespace-pre-wrap text-[15px] leading-7">{provision.content}</p>

          {provision.in_force_notes.length > 0 && (
            <div className="space-y-1">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Note in the source</h3>
              {provision.in_force_notes.map((note) => (
                <p key={note} className="text-sm text-muted-foreground">{note}</p>
              ))}
            </div>
          )}

          <div className="space-y-2 border-t pt-4 text-sm">
            <p className="text-muted-foreground">
              {provision.statute}
              {provision.source_version && `, ${provision.source_version}`}
              {pages(provision)}
            </p>
            {provision.source_url && (
              <a
                href={provision.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 font-medium underline underline-offset-4"
              >
                Open the official source <ExternalLink className="size-3.5" aria-hidden />
              </a>
            )}
          </div>
        </>
      )}

      {/* Traceability, not verification (core contribution 2). */}
      <p className="rounded-lg bg-muted p-3 text-xs leading-5 text-muted-foreground">
        This is the provision the statement was taken from. GetRight does not check that it legally supports the statement.
      </p>
    </div>
  )
}

function describe(provision: Provision): string {
  const title = provision.section_title ? `${provision.section_title}. ` : ''
  return `${title}${provision.jurisdiction}`
}

function pages(provision: Provision): string {
  if (!provision.source_page) return ''
  if (provision.source_page_end && provision.source_page_end !== provision.source_page) {
    return `, pages ${provision.source_page} to ${provision.source_page_end}`
  }
  return `, page ${provision.source_page}`
}

// Text that is not current law gets a warning above it (prompt rule 6 says the same to the model).
function StatusBanner({ provision, onOpen }: { provision: Provision; onOpen: (chunkId: string) => void }) {
  let message: string | null = null
  if (provision.status === 'deleted') {
    message = provision.deleted_by ? `Deleted by ${provision.deleted_by}. This is not current law.` : 'Deleted. This is not current law.'
  } else if (provision.status === 'omitted') {
    message = 'Omitted from the published text. This is not current law.'
  } else if (provision.status === 'not_yet_in_force') {
    message = 'Not yet in force.'
  } else if (provision.status === 'superseded') {
    message = 'A later amendment changed this provision. Read it together with the amending provision.'
  }

  return (
    <>
      {message && (
        <div className="space-y-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
          <p className="flex gap-2">
            <TriangleAlert className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden />
            <span>{message}</span>
          </p>
          {provision.amended_by.map((id) => (
            <button
              key={id}
              type="button"
              onClick={() => onOpen(id)}
              className="ml-6 block font-medium underline underline-offset-4"
            >
              Open the amending provision ({id})
            </button>
          ))}
        </div>
      )}
      {provision.commencement && (
        <p className="text-sm text-muted-foreground">In force from {provision.commencement}.</p>
      )}
    </>
  )
}
