import { describe, expect, it } from 'vitest'

import { langOf } from './format'

describe('The language of a written text, for a screen reader (B#10)', () => {
  it('marks Arabic letters as Arabic', () => {
    expect(langOf('بدّي أوغمنتين')).toBe('ar')
    // A brand name in Latin letters inside an Arabic sentence is still Arabic.
    expect(langOf('بدي Panadol من صيدلية قريبة')).toBe('ar')
  })

  it('leaves English and Arabizi to the page, which is English', () => {
    expect(langOf('I need Panadol')).toBeUndefined()
    expect(langOf('baddi concor 5, 3a2ilti')).toBeUndefined()
    expect(langOf('')).toBeUndefined()
    expect(langOf(null)).toBeUndefined()
  })
})
