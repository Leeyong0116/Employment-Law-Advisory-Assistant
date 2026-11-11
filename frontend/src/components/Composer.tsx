import { ArrowUp } from 'lucide-react'
import type { Region } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { REGIONS } from '@/lib/regions'

const MAX_QUERY_CHARS = 2000 // the API's limit

type ComposerProps = {
  question: string
  onQuestionChange: (question: string) => void
  region: Region | null
  onRegionChange: (region: Region) => void
  canSend: boolean
  onSend: () => void
}

// The question box pinned at the bottom of the page: text, region, Send, disclaimer.
export function Composer({ question, onQuestionChange, region, onRegionChange, canSend, onSend }: ComposerProps) {
  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends; Shift+Enter is a new line; Enter while typing with an input method (IME) is left alone.
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      if (canSend) onSend()
    }
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        if (canSend) onSend()
      }}
      className="space-y-2"
    >
      <div className="rounded-3xl border bg-card shadow-sm transition-shadow focus-within:shadow-md focus-within:ring-[3px] focus-within:ring-ring/20">
        <label htmlFor="question" className="sr-only">Your question</label>
        <Textarea
          id="question"
          value={question}
          onChange={(event) => onQuestionChange(event.target.value)}
          onKeyDown={handleKeyDown}
          maxLength={MAX_QUERY_CHARS}
          rows={1}
          placeholder="Ask about wages, working hours, leave or termination"
          className="max-h-48 min-h-12 resize-none border-0 bg-transparent px-5 pt-4 text-[15px] shadow-none focus-visible:ring-0 dark:bg-transparent"
        />
        <div className="flex items-center justify-between gap-2 px-3 pb-3">
          <Select value={region ?? ''} onValueChange={(value) => onRegionChange(value as Region)}>
            <SelectTrigger aria-label="Where do you work?" className="h-8 w-auto max-w-[75%] rounded-full text-sm">
              <SelectValue placeholder="Where do you work?" />
            </SelectTrigger>
            <SelectContent>
              {REGIONS.map((r) => (
                <SelectItem key={r.value} value={r.value}>{r.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button type="submit" size="icon" disabled={!canSend} aria-label="Send" className="size-9 rounded-full">
            <ArrowUp aria-hidden />
          </Button>
        </div>
      </div>
      {/* Copy of DISCLAIMER in src/generation/schema.py; keep the two texts the same. */}
      <p className="text-center text-xs leading-5 text-muted-foreground">
        GetRight gives legal information, not legal advice. Check the cited provisions, and contact the Department of
        Labour or a lawyer about your own situation.
      </p>
    </form>
  )
}
