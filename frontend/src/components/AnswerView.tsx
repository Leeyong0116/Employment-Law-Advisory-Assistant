import { useState } from 'react'
import type { GeneratedAnswer, Citation } from '@/api/types'

type AnswerViewProps = { answer: GeneratedAnswer }

export function AnswerView({ answer }: AnswerViewProps) {
    const pieces = (answer.answer ?? '').split(/(\[\d+\])/)
    const [selected, setSelected] = useState<Citation | null>(null)


    return (
        <div className="space-y-2">
            <p className="text-sm text-muted-foreground">Status: {answer.status}</p>
            <p className="whitespace-pre-wrap">

                {/* list reference when hover number pill  */}
                {pieces.map((piece, index) => {
                    const citation = answer.citations.find((c) => `[${c.number}]` === piece)
                    if (citation) {
                        return (
                            <button key={index} type="button" title={citation.citation} onClick={() => setSelected(citation)} className="rounded bg-muted px-1 text-xs font-medium">
                                {piece}
                            </button>
                        )
                    }
                    return <span key={index}>{piece}</span>
                })}

            </p>

            {/* list reference  */}
            {answer.citations.length > 0 && (
                <div className="space-y-1">
                    <h2 className="text-sm font-semibold">Sources</h2>
                    <ol className="space-y-2">
                        {answer.citations.map((citation) => (
                            <li key={citation.chunk_id} className="text-sm">
                                <p>
                                    [{citation.number}] {citation.citation} {citation.section_title}
                                </p>
                                <p className="text-muted-foreground">{citation.jurisdiction}</p>
                            </li>
                        ))}
                    </ol>
                </div>
            )}
            {selected && <p>Selected: {selected.citation}</p>}

        </div>
    )
}
