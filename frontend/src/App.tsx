import { useState } from 'react'
import { askQuestion } from '@/api/client'
import type { GeneratedAnswer } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'


export default function App() {
  const[question, setQuestion] = useState('')
  const[result, setResult] = useState<GeneratedAnswer | null>(null)

  async function handleSend(){
      // TEMPORARY: region is fixed until the dropdown is added in step 4b.
      const answer = await askQuestion(question, 'peninsular')
      setResult(answer)
  }

  return(
    <main className="mx-auto max-w-3x1 space-y-4 p-4">
      <h1 className="text-2x font-semibold"> GetRight</h1>

      <Textarea
      value={question}
      onChange={(event) => setQuestion(event.target.value)}
      placeholder=" Ask about your employment rights "
      />
      <Button onClick={handleSend}>Send</Button>

      {result && (
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground"> Status: {result.status}</p>
          <p className="whitespace-pre-wrap">{result.answer}</p>
        </div>
      )}
      </main>   
  )
}