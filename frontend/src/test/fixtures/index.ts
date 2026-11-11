// Real API responses captured on 2026-11-11 (DeepSeek generator, index 459843bf28ba).
// JSON imports are typed loosely (status: string), so they are cast to the API types here.
import type { GeneratedAnswer, Provision } from '@/api/types'
import abstainedJson from './answer_abstained.json'
import answeredJson from './answer_answered.json'
import dismissalJson from './answer_dismissal_m4v3.json'
import insufficientJson from './answer_insufficient.json'
import sarawakJson from './answer_sarawak_maternity.json'
import a1754S24 from './provision_A1754_s24.json'
import eaS60E1 from './provision_EA1955_s60E_1.json'
import eaS9 from './provision_EA1955_s9.json'
import swkS84 from './provision_SWK76_s84_1.json'

export const answered = answeredJson as unknown as GeneratedAnswer          // EA s.60E, 5 citations
export const abstained = abstainedJson as unknown as GeneratedAnswer        // gate: low_score
export const insufficient = insufficientJson as unknown as GeneratedAnswer  // model declined
export const dismissal = dismissalJson as unknown as GeneratedAnswer        // prompt m4-v3, with limits (2026-11-12)
export const sarawakMaternity = sarawakJson as unknown as GeneratedAnswer   // A1754 s.24, with a note

export const provisions: Record<string, Provision> = {
  EA1955_s60E_1: eaS60E1 as unknown as Provision,   // in force
  SWK76_s84_1: swkS84 as unknown as Provision,      // superseded, amended_by A1754_s24
  A1754_s24: a1754S24 as unknown as Provision,      // amendment, commencement 2025-05-01
  EA1955_s9: eaS9 as unknown as Provision,          // deleted, with an in-force note
}
