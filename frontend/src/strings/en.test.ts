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

describe('One name for one thing, and one for one (B wording table)', () => {
  it('writes one day and one minute in the singular', () => {
    expect(strings.offer.lastsYour(1)).toBe('Lasts your 1 day')
    expect(strings.offer.lastsYour(7)).toBe('Lasts your 7 days')
    expect(strings.offer.doesntLast(1, '20 Nov')).toContain('before your 1 day ends')
    expect(strings.admin.clock.ahead(1)).toBe('1 minute ahead of the real time.')
  })

  it('calls a request a request, and spells licence one way', () => {
    expect(strings.request.cancelTitle).toContain('request')
    expect(Object.values(strings.request.closed).join(' ')).not.toMatch(/the search has ended|this search/i)
    expect(strings.errors.LICENSE_TAKEN).toContain('licence')
  })
})
