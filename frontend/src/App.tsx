import { useState} from 'react'
import { askQuestion } from '@/api/client'
import type { GeneratedAnswer, Region } from '@/api/types'
import { Button } from '@/components/ui/button'
import { AnswerView } from '@/components/AnswerView'
import { Textarea } from '@/components/ui/textarea'
import {Select, SelectContent, SelectItem, SelectTrigger, SelectValue} from '@/components/ui/select'




export default function App() {
  const[question, setQuestion] = useState('')
  const[region, setRegion] = useState<Region | null>(null)
  const[result, setResult] = useState<GeneratedAnswer | null>(null)
  const[loading, setLoading] = useState(false)
  const[error, setError] = useState<string | null>(null)
  const canSend = question.trim().length > 0 && !loading && region !== null



  async function handleSend(){
      if (!region) return
      setLoading(true)
      setError(null)
      setResult(null)
      try{
      const answer = await askQuestion(question, region)
      setResult(answer)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Something went wrong.')
      } finally {
        setLoading(false)
      }
  }

  return(
    <main className="mx-auto max-w-3xl space-y-4 p-4">
      <h1 className="text-2xl font-semibold">GetRight</h1>

      <Textarea
      value={question}
      onChange={(event) => setQuestion(event.target.value)}
      placeholder="Ask about your employment rights"
      />
      <Select value={region ?? ''} onValueChange={(value) => setRegion(value as Region)}>
        <SelectTrigger>
          <SelectValue placeholder="Where do you work?" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="peninsular">Peninsular Malaysia and Labuan</SelectItem>
          <SelectItem value="sabah">Sabah</SelectItem>
          <SelectItem value="sarawak">Sarawak</SelectItem>
        </SelectContent>
      </Select>
      <Button onClick={handleSend} disabled={!canSend}>
        {loading ? 'Sending...' : 'Send'}
      </Button>
      {/* copy of DISCLAIMER from src/generation/schema.py  */}
      <p className="text-sm text-muted-foreground">
        GetRight gives legal information, not legal advice. Check the cited provisions, and contact the Department of Labour or a lawyer about your own situation.
      </p>

      {error && (
        <div className="space-y-2">
          <p role="alert" className="text-red-500">{error}</p>
          <Button onClick={handleSend} disabled={!canSend}>
            Retry
          </Button>
        </div>
      )}


      {result && <AnswerView answer={result} />}
      </main>   
  )
}