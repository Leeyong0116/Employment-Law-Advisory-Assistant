import { Fragment } from 'react'
import { Info, TriangleAlert } from 'lucide-react'
import type { Citation, GeneratedAnswer } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { parseAnswer, type Statement } from '@/lib/answerText'
import { chipLabel } from '@/lib/citations'

type AnswerViewProps = {
  answer: GeneratedAnswer
  selected: number | null // the citation open in the source panel
  onSelect: (number: number) => void
}

// Labels for citations that are not current law (chunk status from the corpus).
const STATUS_LABELS: Record<string, string> = {
  deleted: 'Deleted',
  omitted: 'Omitted',
  superseded: 'Amended later',
  not_yet_in_force: 'Not yet in force',
}

export function AnswerView({ answer, selected, onSelect }: AnswerViewProps) {
  const byNumber = new Map(answer.citations.map((c) => [c.number, c]))

  return (
    <section aria-label="Answer" className="space-y-6">
      {answer.status === 'abstained' && answer.abstention && (
        <Notice title={answer.abstention.reason === 'language' ? 'English questions only' : 'Outside what GetRight covers'}>
          <p className="whitespace-pre-wrap">{answer.abstention.message}</p>
        </Notice>
      )}

      {answer.status === 'insufficient_context' && (
        <Notice title="No answer from the statutes held">
          <p>
            GetRight found related provisions, but they do not answer this question, so it did not write an answer.
            For help with your situation, contact the Department of Labour (JTKSM, JTK Sabah or JTK Sarawak).
          </p>
        </Notice>
      )}

      {answer.status === 'answered' && (
        <AnswerText text={answer.answer ?? ''} citations={byNumber} selected={selected} onSelect={onSelect} />
      )}

      {answer.limits && (
        <aside
          role="note"
          aria-label="What the sources cannot tell you"
          className="flex gap-3 rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm leading-6"
        >
          <TriangleAlert className="mt-1 size-4 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden />
          <div>
            <p className="font-semibold">What the sources cannot tell you</p>
            <p>{answer.limits}</p>
          </div>
        </aside>
      )}

      {answer.external_dependencies.length > 0 && (
        <div className="space-y-1 text-sm text-muted-foreground">
          {answer.external_dependencies.map((statute) => (
            <p key={statute}>Part of this depends on {statute}, which GetRight does not hold.</p>
          ))}
        </div>
      )}

      {answer.notes.length > 0 && (
        <div className="space-y-2 rounded-xl border bg-muted/40 p-4 text-sm">
          <h2 className="font-semibold">Note</h2>
          {answer.notes.map((note) => (
            <p key={note} className="leading-6 text-muted-foreground">{note}</p>
          ))}
        </div>
      )}

      {answer.citations.length > 0 && (
        <div className="space-y-2">
          <h2 id="sources-heading" className="text-sm font-semibold">Sources</h2>
          <ol aria-labelledby="sources-heading" className="space-y-2">
            {answer.citations.map((citation) => (
              <li key={citation.chunk_id}>
                <button
                  type="button"
                  aria-pressed={citation.number === selected}
                  onClick={() => onSelect(citation.number)}
                  className="flex w-full gap-3 rounded-xl border p-3 text-left text-sm transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 aria-pressed:border-foreground/40 aria-pressed:bg-muted/60"
                >
                  <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold">
                    {citation.number}
                  </span>
                  <span className="min-w-0 flex-1">
                    {/* Label and heading straight from citation fields (core contribution 1). */}
                    <span className="font-medium">{citation.citation}</span>
                    {citation.section_title && <span className="text-muted-foreground"> {citation.section_title}</span>}
                    {STATUS_LABELS[citation.status] && (
                      <Badge variant="outline" className="ml-2 align-middle">{STATUS_LABELS[citation.status]}</Badge>
                    )}
                  </span>
                </button>
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  )
}

type AnswerTextProps = {
  text: string
  citations: Map<number, Citation>
  selected: number | null
  onSelect: (number: number) => void
}

// Headings, lists and paragraphs from the m4-v3 answer. Each sentence keeps the markers
// that close it; the sentence of the selected citation is highlighted.
function AnswerText({ text, citations, selected, onSelect }: AnswerTextProps) {
  const blocks = parseAnswer(text, new Set(citations.keys()))
  const inline = (statements: Statement[]) =>
    statements.map((s, i) => (
      <Fragment key={i}>
        {selected !== null && s.markers.includes(selected) ? (
          <mark className="rounded-sm bg-amber-200/70 text-foreground dark:bg-amber-400/25">{s.text}</mark>
        ) : (
          s.text
        )}
        {s.markers.map((n) => (
          <Chip key={n} citation={citations.get(n)!} active={n === selected} onSelect={onSelect} />
        ))}
      </Fragment>
    ))

  return (
    <div className="space-y-3 text-[15px] leading-7">
      {blocks.map((block, i) => {
        if (block.type === 'heading') {
          return <h3 key={i} className="pt-2 text-base font-semibold">{inline(block.inline)}</h3>
        }
        if (block.type === 'list') {
          const List = block.ordered ? 'ol' : 'ul'
          return (
            <List key={i} className={`space-y-1.5 pl-5 ${block.ordered ? 'list-decimal' : 'list-disc'} marker:text-muted-foreground`}>
              {block.items.map((item, j) => <li key={j} className="pl-1">{inline(item)}</li>)}
            </List>
          )
        }
        return <p key={i}>{inline(block.inline)}</p>
      })}
    </div>
  )
}

// A numbered chip after the punctuation it follows. The number shows; hover and screen
// readers get the section reference too.
function Chip({ citation, active, onSelect }: { citation: Citation; active: boolean; onSelect: (n: number) => void }) {
  const label = chipLabel(citation)
  return (
    <button
      type="button"
      title={label}
      aria-label={`Source ${citation.number}: ${label}`}
      aria-pressed={active}
      onClick={() => onSelect(citation.number)}
      className="ml-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-muted px-1.5 align-text-top text-[11px] font-semibold text-muted-foreground transition-colors hover:bg-foreground hover:text-background focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 aria-pressed:bg-foreground aria-pressed:text-background"
    >
      {citation.number}
    </button>
  )
}

// Abstention and refusal are information, not errors: neutral colours and an info icon.
function Notice({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div role="status" className="flex gap-3 rounded-xl border bg-muted/40 p-4 text-sm leading-6">
      <Info className="mt-1 size-4 shrink-0 text-muted-foreground" aria-hidden />
      <div className="space-y-1">
        <h2 className="font-semibold">{title}</h2>
        {children}
      </div>
    </div>
  )
}
