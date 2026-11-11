import { parseAnswer, parseInline } from './answerText'

const known = new Set([1, 2, 3])

test('a statement ends at its markers; the full stop moves before the chip', () => {
  expect(parseInline('Eight days [1]. Twelve days [2][3].', known)).toEqual([
    { text: 'Eight days.', markers: [1] },
    { text: ' Twelve days.', markers: [2, 3] },
  ])
})

test('a marker written after the full stop gives the same result', () => {
  expect(parseInline('Eight days. [1] More text.', known)).toEqual([
    { text: 'Eight days.', markers: [1] },
    { text: ' More text.', markers: [] },
  ])
})

test('an unknown marker stays as text', () => {
  expect(parseInline('Something [9].', known)).toEqual([{ text: 'Something [9].', markers: [] }])
})

test('headings, bullet lists and paragraphs become blocks', () => {
  const blocks = parseAnswer('Direct answer [1].\n\n## When it is allowed\n- First [1].\n- Second [2].\n\nClosing text.', known)
  expect(blocks.map((b) => b.type)).toEqual(['paragraph', 'heading', 'list', 'paragraph'])
  expect(blocks[1]).toEqual({ type: 'heading', inline: [{ text: 'When it is allowed', markers: [] }] })
  expect(blocks[2]).toMatchObject({ type: 'list', ordered: false, items: [[{ text: 'First.', markers: [1] }], [{ text: 'Second.', markers: [2] }]] })
})

test('numbered lists and stray bold markers are handled', () => {
  const blocks = parseAnswer('1. One [1].\n2. **Two** [2].', known)
  expect(blocks).toEqual([{ type: 'list', ordered: true, items: [[{ text: 'One.', markers: [1] }], [{ text: 'Two.', markers: [2] }]] }])
})
