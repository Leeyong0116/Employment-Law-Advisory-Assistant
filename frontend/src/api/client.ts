import type{ GeneratedAnswer, Region} from './types'

const FALLBACK_MESSAGE = 'GetRight could not reach the server. Please try again.'

export async function askQuestion(query: string, region: Region):Promise<GeneratedAnswer>{
    let response: Response
    try{
        response = await fetch('/api/ask', {
        method:'POST',
        headers:{ 'Content-Type': 'application/json' },
            body: JSON.stringify({ query, region}),
        }) 
    }
        catch{
            throw new Error(FALLBACK_MESSAGE)
        }
    
    if (!response.ok) {
        throw new Error(await errorMessage(response))
    }
    return await response.json()
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body.message === 'string') return body.message
  } catch {
    // not JSON, e.g. the Vite proxy answering because FastAPI is not running
  }
  return FALLBACK_MESSAGE
}
