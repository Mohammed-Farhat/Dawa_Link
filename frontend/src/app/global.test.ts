import { describe, expect, it } from 'vitest'

import { contrast } from '../test/contrast'

// The look's rules that a page test can't see (jsdom loads no stylesheet and paints
// nothing): read from the stylesheet itself, so a later edit can't quietly undo them.

// Read from the disk: the tests' setting `css: false` empties every stylesheet that is
// imported, `?raw` included. The website's own code has no Node types, hence the name.
// The tests run from frontend/ (npm test, npx vitest).
const fs = (await import(/* @vite-ignore */ ['node', 'fs'].join(':'))) as {
  readFileSync: (file: string, encoding: 'utf8') => string
}
const css = fs.readFileSync('src/app/global.css', 'utf8')

const text = css.replace(/\/\*[\s\S]*?\*\//g, '')

/** Every innermost rule: its selector, written on one line, and its declarations. */
const RULES = [...text.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([, selector, body]) => ({
  selector: selector!.replace(/\s+/g, ' ').trim(),
  body: body!,
}))

function declarations(selector: string): Record<string, string> {
  const found = RULES.filter((rule) => rule.selector === selector)
  expect(found, `a rule for ${selector}`).not.toHaveLength(0)
  const out: Record<string, string> = {}
  for (const { body } of found) {
    for (const line of body.split(';')) {
      const at = line.indexOf(':')
      if (at > 0) out[line.slice(0, at).trim()] = line.slice(at + 1).trim()
    }
  }
  return out
}

const ROOT = declarations(':root')
const px = (value: string | undefined) => Number(value?.replace('px', ''))

describe('The stylesheet', () => {
  it('draws one focus ring everywhere: 2 px, green (B#45, docs/11 §9)', () => {
    const outlines = [...text.matchAll(/(?:^|[;{\s])outline\s*:\s*([^;}]+)/g)].map(([, value]) => value!.trim())
    expect(outlines.length).toBeGreaterThan(0)
    for (const value of outlines) expect(['none', '2px solid var(--green)']).toContain(value)
  })

  it('colours a chosen choice blue in every picker, and draws tabs as a white segment on a grey track (B#46)', () => {
    expect(declarations(".chip[aria-pressed='true']").background).toBe('var(--blue)')
    expect(declarations(".tabs__tab[aria-checked='true']").background).toBe('var(--blue)')
    expect(declarations(".tabs[role='tablist']").background).toBe('var(--line)')
    expect(declarations(".tabs[role='tablist'] .tabs__tab[aria-selected='true']").background).toBe('var(--white)')
    // Navy is the ink of text, never the colour of a choice.
    for (const rule of RULES.filter((one) => /\[aria-(pressed|checked|selected)='true'\]/.test(one.selector))) {
      expect(rule.body, rule.selector).not.toMatch(/background:\s*var\(--ink\)/)
    }
  })

  it('writes what you save at one size, and one bigger size on the ticket (B#40)', () => {
    expect(declarations('.saving')['font-size']).toBe('14px')
    expect(px(declarations('.saving--big')['font-size'])).toBeGreaterThan(14)
  })

  it("gives every field one height, one radius and an edge that can be seen (B#18)", () => {
    expect(px(ROOT['--field-height'])).toBeGreaterThanOrEqual(44)
    expect(px(ROOT['--field-height'])).toBeLessThanOrEqual(48)
    // A field's edge is 3:1 on white (WCAG 1.4.11), a hint 4.5:1 (1.4.3).
    expect(contrast(ROOT['--field']!, ROOT['--white']!)).toBeGreaterThanOrEqual(3)
    expect(contrast(ROOT['--ink-hint']!, ROOT['--white']!)).toBeGreaterThanOrEqual(4.5)
    expect(contrast(ROOT['--ink-soft']!, ROOT['--white']!)).toBeGreaterThanOrEqual(4.5)
    const library = declarations('.mantine-Input-wrapper.mantine-Input-wrapper')
    expect(library['--input-height-sm']).toBe('var(--field-height)')
    expect(library['--input-radius']).toBe('var(--field-radius)')
    const ours = declarations('.time-input, .quantity-input')
    expect(ours.height).toBe('var(--field-height)')
    expect(ours['border-radius']).toBe('var(--field-radius)')
    expect(ours.border).toContain('var(--field)')
    expect(declarations('.text-area')['border-radius']).toBe('var(--field-radius)')
    // The library's edge is ours, set on the wrapper: its error rule there stays red.
    expect(declarations("[data-mantine-color-scheme='light'] .mantine-Input-wrapper[data-variant='default']")['--input-bd']).toBe(
      'var(--field)',
    )
  })

  it("makes the small buttons 44 px for a finger (B#41, docs/11 §9)", () => {
    expect(declarations('.chat__new')['min-height']).toBe('44px')
    expect(declarations('.chat__tool').height).toBe('44px')
    expect(declarations('.chat__tool').width).toBe('44px')
    const zoom = declarations('.map.leaflet-container .leaflet-bar a')
    expect([zoom.width, zoom.height]).toEqual(['44px', '44px'])
    expect(declarations('.radio-row')['min-height']).toBe('44px')
  })
})
