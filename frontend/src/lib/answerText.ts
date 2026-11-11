// Turns the answer text (prompt m4-v3) into blocks for display. The text itself is not
// changed: only its layout is read ("## " headings, "- " or "1. " list items, paragraphs)
// and each sentence is paired with the markers that close it, so a clicked citation can
// highlight its sentence. React escapes all text, so model output cannot inject HTML.

export type Statement = { text: string; markers: number[] } // markers empty: text with no citation
export type Block =
  | { type: 'heading'; inline: Statement[] }
  | { type: 'paragraph'; inline: Statement[] }
  | { type: 'list'; ordered: boolean; items: Statement[][] }

const MARKER = /^\[(\d+)\]$/
const LEADING_PUNCTUATION = /^[.,;:!?)]+/

/** Splits one line into statements. A marker group ends a statement; a full stop or comma
 * right after the markers moves before them, so the chip sits after the punctuation. */
export function parseInline(line: string, known: Set<number>): Statement[] {
  const out: Statement[] = []
  let text = ''
  let markers: number[] = []

  const close = () => {
    if (markers.length) {
      out.push({ text: text.trimEnd(), markers })
      text = ''
      markers = []
    }
  }

  for (const token of line.replace(/\*\*/g, '').split(/(\[\d+\])/)) {
    if (!token) continue
    const match = MARKER.exec(token)
    if (match && known.has(Number(match[1]))) {
      if (!markers.includes(Number(match[1]))) markers.push(Number(match[1]))
      continue
    }
    if (markers.length) {
      const punctuation = LEADING_PUNCTUATION.exec(token)?.[0] ?? ''
      text = text.trimEnd() + punctuation
      close()
      text = token.slice(punctuation.length)
    } else {
      text += token
    }
  }
  close()
  if (text.trim()) out.push({ text: text.trimEnd(), markers: [] })
  return out
}

export function parseAnswer(answer: string, known: Set<number>): Block[] {
  const blocks: Block[] = []
  for (const raw of answer.split('\n')) {
    const line = raw.trim()
    if (!line) continue
    const heading = /^#{1,6}\s+(.*)$/.exec(line)
    const bullet = /^[-*•]\s+(.*)$/.exec(line)
    const numbered = /^\d+[.)]\s+(.*)$/.exec(line)
    if (heading) {
      blocks.push({ type: 'heading', inline: parseInline(heading[1], known) })
    } else if (bullet || numbered) {
      const ordered = Boolean(numbered)
      const item = parseInline((bullet ?? numbered)![1], known)
      const last = blocks.at(-1)
      if (last?.type === 'list' && last.ordered === ordered) last.items.push(item)
      else blocks.push({ type: 'list', ordered, items: [item] })
    } else {
      blocks.push({ type: 'paragraph', inline: parseInline(line, known) })
    }
  }
  return blocks
}
