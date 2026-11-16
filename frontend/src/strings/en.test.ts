import { describe, expect, it } from 'vitest'

// The API document itself, as text: the list of codes is read from its table.
import apiDoc from '../../../docs/06_api.md?raw'
import { errorMessage, strings } from './en'

// The API answers a failure with a stable code (docs/06 §3.2), and the website says what
// it means in its own words. A code with no words would show "Something went wrong on
// our side" for something the client can understand and act on.

function documentedCodes(): string[] {
  const codes: string[] = []
  for (const row of apiDoc.matchAll(/^\| (`[A-Z_]+`(?: \/ `[A-Z_]+`)*) \| \d{3} \|/gm)) {
    codes.push(...(row[1].match(/[A-Z_]+/g) ?? []))
  }
  return codes
}

describe('What the website says for each error code', () => {
  it('has words of its own for every code of the API', () => {
    const codes = documentedCodes()

    expect(codes.length).toBeGreaterThan(50)
    expect(codes.filter((code) => !(code in strings.errors))).toEqual([])
  })

  it('never shows a raw code, and falls back to the general sentence', () => {
    expect(Object.values(strings.errors).filter((words) => /[A-Z]{2,}_[A-Z]/.test(words))).toEqual([])
    expect(errorMessage('A_CODE_NOBODY_KNOWS')).toBe(strings.errors.INTERNAL_ERROR)
  })
})
