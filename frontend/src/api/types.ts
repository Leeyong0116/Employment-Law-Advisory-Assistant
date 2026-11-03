// Short names for the types generated from the FastAPI schema (schema.d.ts).
// Regenerate with `npm run gen:types` after the backend schema changes.
import type { components } from './schema'

type Schemas = components['schemas']

export type GeneratedAnswer = Schemas['GeneratedAnswer']
export type Citation = Schemas['Citation']
export type Provision = Schemas['Provision']
export type Meta = Schemas['Meta']
export type ApiError = Schemas['ApiError']
export type Region = NonNullable<Schemas['AskRequest']['region']>
