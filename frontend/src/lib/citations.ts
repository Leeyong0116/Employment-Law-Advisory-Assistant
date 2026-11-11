import type { Citation } from '@/api/types'

/** The section part of a citation label, e.g. "s. 14(1)" from "Employment Act 1955, s. 14(1)".
 * Cut from the API's own label, never built from parts (core contribution 1). */
export function sectionRef(citation: Citation): string {
  const prefix = `${citation.statute}, `
  return citation.citation.startsWith(prefix) ? citation.citation.slice(prefix.length) : citation.citation
}

/** "s. 14(1), Employment Act 1955": what a chip says on hover and to screen readers. */
export function chipLabel(citation: Citation): string {
  const ref = sectionRef(citation)
  return ref === citation.citation ? ref : `${ref}, ${citation.statute}`
}
